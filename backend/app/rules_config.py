"""Правила соответствия техники этапам.

Основной источник — таблицы core.StageRule/ConfusablePair/KnownLimitation/MatchingSettings
в PostgreSQL (редактируются через Django admin). Резервный откат при
недоступности БД — data/config/equipment_rules.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import django_bridge
from .config import EQUIPMENT_RULES_PATH


@dataclass(frozen=True)
class StageRule:
    stage_id: str
    work_name: str
    required: list[str]
    allowed: list[str]
    alternatives_note: str
    required_quantities: dict[str, int] = field(default_factory=dict)
    """Ключ класса → минимальное количество единиц техники (план для Plan vs Fact).
    Классы без явного количества (старый формат без чисел) трактуются как min_quantity=1."""
    required_labels_ru: dict[str, str] = field(default_factory=dict)
    """Ключ класса → русское название из словаря. Нужен как запасной источник подписи
    в Plan vs Fact, когда техника вообще не обнаружена (нет детекции — неоткуда взять
    label_ru), иначе в объяснении отклонения утекает сырой английский class_key."""


@dataclass(frozen=True)
class KnownLimitation:
    class_key: str
    label_ru: str
    issue: str
    description: str


@dataclass(frozen=True)
class EquipmentRules:
    stage_rules: dict[str, StageRule]
    ambiguity_margin: float
    confusable_class_pairs: list[tuple[str, str]]
    known_limitations: list[KnownLimitation] = field(default_factory=list)


def _parse_required_field(raw_required) -> tuple[list[str], dict[str, int]]:
    """`required` в YAML может быть списком ключей (старый формат, min_quantity=1)
    или словарём ключ → количество (новый формат с количествами)."""
    if raw_required is None:
        return [], {}
    if isinstance(raw_required, dict):
        quantities = {key: int(qty) for key, qty in raw_required.items()}
        return sorted(quantities), quantities
    keys = list(raw_required)
    return keys, dict.fromkeys(keys, 1)


def _load_equipment_rules_from_file(path: Path = EQUIPMENT_RULES_PATH) -> EquipmentRules:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    # Русские подписи классов берутся из словаря, а не из equipment_rules.yaml —
    # там названий нет вообще, только ключи.
    from .vocabulary import load_vocabulary

    vocab_classes = load_vocabulary().classes

    stage_rules = {}
    for stage_id, entry in (data.get("stage_rules") or {}).items():
        required, required_quantities = _parse_required_field(entry.get("required"))
        required_labels_ru = {
            key: vocab_classes[key].label_ru for key in required_quantities if key in vocab_classes
        }
        stage_rules[stage_id] = StageRule(
            stage_id=stage_id,
            work_name=entry["work_name"],
            required=required,
            allowed=list(entry.get("allowed") or []),
            alternatives_note=(entry.get("alternatives_note") or "").strip(),
            required_quantities=required_quantities,
            required_labels_ru=required_labels_ru,
        )

    pairs = [tuple(pair) for pair in data.get("confusable_class_pairs") or []]
    limitations = [
        KnownLimitation(
            class_key=entry["class_key"],
            label_ru=entry["label_ru"],
            issue=entry["issue"],
            description=(entry.get("description") or "").strip(),
        )
        for entry in data.get("known_limitations") or []
    ]

    return EquipmentRules(
        stage_rules=stage_rules,
        ambiguity_margin=float(data.get("ambiguity_margin", 0.15)),
        confusable_class_pairs=pairs,
        known_limitations=limitations,
    )


def _load_equipment_rules_from_db(site=None) -> EquipmentRules:
    from core.models import ConfusablePair, MatchingSettings
    from core.models import KnownLimitation as KnownLimitationRow
    from core.models import StageRule as StageRuleRow

    stage_rule_qs = StageRuleRow.objects.select_related("stage").prefetch_related(
        "required_items__vocabulary_class", "allowed"
    )
    if site is not None:
        stage_rule_qs = stage_rule_qs.filter(stage__zone__site=site)
    else:
        stage_rule_qs = stage_rule_qs.filter(stage__zone__site__is_legacy=True)

    stage_rules: dict[str, StageRule] = {}
    for row in stage_rule_qs:
        required_quantities = {
            item.vocabulary_class.key: item.min_quantity for item in row.required_items.all()
        }
        required_labels_ru = {
            item.vocabulary_class.key: item.vocabulary_class.label_ru
            for item in row.required_items.all()
        }
        stage_rules[row.stage.external_id] = StageRule(
            stage_id=row.stage.external_id,
            work_name=row.stage.work_name,
            required=sorted(required_quantities),
            allowed=[c.key for c in row.allowed.all()],
            alternatives_note=row.alternatives_note,
            required_quantities=required_quantities,
            required_labels_ru=required_labels_ru,
        )

    pairs = [
        (row.class_a.key, row.class_b.key)
        for row in ConfusablePair.objects.select_related("class_a", "class_b")
    ]
    limitations = [
        KnownLimitation(
            class_key=row.vocabulary_class.key,
            label_ru=row.vocabulary_class.label_ru,
            issue=row.issue,
            description=row.description,
        )
        for row in KnownLimitationRow.objects.select_related("vocabulary_class")
    ]
    settings_row = MatchingSettings.objects.first()
    ambiguity_margin = settings_row.ambiguity_margin if settings_row else 0.15

    if not stage_rules:
        if site is not None:
            # Новый проект без настроенных правил — честное пустое состояние, анализ недоступен.
            return EquipmentRules(stage_rules={}, ambiguity_margin=0.15, confusable_class_pairs=[], known_limitations=[])
        raise ValueError("Правила legacy-проекта в БД пусты — выполните `python manage.py seed_demo_data`")

    return EquipmentRules(
        stage_rules=stage_rules,
        ambiguity_margin=ambiguity_margin,
        confusable_class_pairs=pairs,
        known_limitations=limitations,
    )


def load_equipment_rules(path: Path = EQUIPMENT_RULES_PATH, site=None) -> EquipmentRules:
    if django_bridge.ensure_django_ready():
        try:
            return _load_equipment_rules_from_db(site=site)
        except Exception:
            if site is not None:
                raise
            django_bridge.logger.exception("Не удалось загрузить правила из БД, откат на файл")
    elif site is not None:
        from fastapi import HTTPException

        raise HTTPException(503, "База данных недоступна")
    return _load_equipment_rules_from_file(path)
