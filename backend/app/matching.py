"""Сопоставление обнаруженной техники с этапами графика.

Реализует методику из плана (раздел «Методика сопоставления»):
  1. Без подтверждённой даты снимка — весь результат «Недостаточно данных».
  2. Активные этапы выбираются по дате и зоне, не по тому, что нашла модель.
  3. Правила читаются из конфигурации (equipment_rules.yaml), не из кода.
  4. Два обязательных отклонения: отсутствие требуемой техники и
     неожиданная техника (вне required+allowed всех активных этапов зоны).
  5. Неопределённость не превращается в тревогу: неоднозначные детекции
     (см. detector.py) не используются как надёжное подтверждение или
     опровержение присутствия класса — они дают «Недостаточно данных».
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .detector import Detection
from .rules_config import EquipmentRules, StageRule
from .schedule import Schedule, Stage

STATUS_NO_DEVIATION = "no_deviation"
STATUS_POSSIBLE_DEVIATION = "possible_deviation"
STATUS_INSUFFICIENT_DATA = "insufficient_data"

STATUS_LABELS_RU = {
    STATUS_NO_DEVIATION: "Отклонений по проверяемым признакам не выявлено",
    STATUS_POSSIBLE_DEVIATION: "Возможное отклонение",
    STATUS_INSUFFICIENT_DATA: "Недостаточно данных",
}


@dataclass
class QuantityCheck:
    class_key: str
    label_ru: str
    required_qty: int
    actual_qty: int
    satisfied: bool


@dataclass
class StageEvaluation:
    stage_id: str
    work_name: str
    zone_id: str
    status: str
    status_label_ru: str
    required: list[str]
    allowed: list[str]
    missing_required: list[str]
    unexpected_detections: list[Detection]
    ambiguous_detections: list[Detection]
    explanation_ru: str
    evidence: list[Detection] = field(default_factory=list)
    quantity_checks: list[QuantityCheck] = field(default_factory=list)


@dataclass
class ObservationEvaluation:
    zone_id: str
    observed_date: date | None
    date_confirmed: bool
    overall_status: str
    overall_status_label_ru: str
    overall_explanation_ru: str
    stage_evaluations: list[StageEvaluation]
    all_detections: list[Detection]


def _zone_allowed_classes(active_stages: list[Stage], rules: EquipmentRules) -> set[str]:
    allowed: set[str] = set()
    for stage in active_stages:
        rule = rules.stage_rules.get(stage.stage_id)
        if rule:
            allowed |= set(rule.required) | set(rule.allowed)
    return allowed


def _confusable_partners_of(class_key: str, confusable_pairs: list[tuple[str, str]]) -> set[str]:
    partners: set[str] = set()
    for a, b in confusable_pairs:
        if class_key == a:
            partners.add(b)
        elif class_key == b:
            partners.add(a)
    return partners


def _evaluate_stage(
    stage: Stage,
    rule: StageRule,
    detections: list[Detection],
    zone_allowed: set[str],
    confusable_pairs: list[tuple[str, str]],
) -> StageEvaluation:
    confident_by_class: dict[str, list[Detection]] = {}
    ambiguous_by_class: dict[str, list[Detection]] = {}
    for detection in detections:
        if not detection.in_taxonomy:
            continue
        bucket = ambiguous_by_class if detection.ambiguous else confident_by_class
        bucket.setdefault(detection.class_key, []).append(detection)

    required_set = set(rule.required)
    confidently_present = required_set & confident_by_class.keys()

    # Важно: неоднозначная детекция выходит под именем "конкурирующего"
    # класса (например, "crane_manipulator"), а не под именем требуемого
    # класса ("excavator"), который мог быть неверно перепутан. Поэтому для
    # каждого неподтверждённого требуемого класса проверяем, не появился ли среди
    # неоднозначных детекций его известный парный класс.
    not_yet_confirmed = required_set - confidently_present
    missing_but_ambiguous = sorted(
        r
        for r in not_yet_confirmed
        if _confusable_partners_of(r, confusable_pairs) & ambiguous_by_class.keys()
    )
    missing_required = sorted(not_yet_confirmed - set(missing_but_ambiguous))

    # План/факт по количеству: считаем только confident-детекции — неоднозначная
    # детекция не должна надёжно увеличивать фактический счёт.
    quantity_checks = [
        QuantityCheck(
            class_key=class_key,
            label_ru=next(
                (d.label_ru for d in confident_by_class.get(class_key, [])),
                rule.required_labels_ru.get(class_key, class_key),
            ),
            required_qty=min_quantity,
            actual_qty=len(confident_by_class.get(class_key, [])),
            satisfied=len(confident_by_class.get(class_key, [])) >= min_quantity,
        )
        for class_key, min_quantity in sorted(rule.required_quantities.items())
    ]

    unexpected = [
        d
        for d in detections
        if d.in_taxonomy and not d.ambiguous and d.class_key not in zone_allowed
    ]
    ambiguous_relevant = [
        d for d in detections if d.ambiguous and (d.class_key in required_set or d.class_key not in zone_allowed)
    ]

    evidence = [d for d in detections if d.in_taxonomy]

    partial_shortfalls = sorted(
        f"{c.label_ru}: план {c.required_qty}, факт {c.actual_qty}"
        for c in quantity_checks
        if not c.satisfied and c.class_key not in missing_required and c.class_key not in missing_but_ambiguous
    )

    if missing_but_ambiguous:
        status = STATUS_INSUFFICIENT_DATA
        pairs = ", ".join(rule.required_labels_ru.get(r, r) for r in missing_but_ambiguous)
        explanation = (
            f"Требуемая техника ({pairs}) могла присутствовать, но обнаружена только как "
            "неоднозначный результат классификации (см. известное ограничение модели: "
            "экскаватор/кран-манипулятор). Нужна ручная проверка снимка."
        )
    elif missing_required:
        status = STATUS_POSSIBLE_DEVIATION
        missing_labels = ", ".join(rule.required_labels_ru.get(r, r) for r in missing_required)
        explanation = (
            f"Не обнаружена требуемая техника для этапа «{rule.work_name}»: "
            f"{missing_labels}. Это может быть отсутствие в видимой зоне, "
            "а не подтверждённый простой — требуется проверка."
        )
    elif partial_shortfalls:
        status = STATUS_POSSIBLE_DEVIATION
        explanation = (
            f"Требуемая техника для этапа «{rule.work_name}» обнаружена в недостаточном количестве: "
            f"{'; '.join(partial_shortfalls)}. Это может быть частичное отсутствие в видимой зоне, "
            "а не подтверждённый простой — требуется проверка."
        )
    elif unexpected:
        status = STATUS_POSSIBLE_DEVIATION
        labels = ", ".join(sorted({d.label_ru for d in unexpected}))
        explanation = (
            f"Обнаружена техника вне разрешённого набора активных работ зоны: {labels}. "
            "Проверьте, не связана ли она с параллельными работами или логистикой."
        )
    elif ambiguous_relevant:
        status = STATUS_INSUFFICIENT_DATA
        explanation = (
            "Есть неоднозначные детекции, которые могут относиться к требуемому или "
            "постороннему классу — автоматически классифицировать нельзя."
        )
    else:
        status = STATUS_NO_DEVIATION
        explanation = (
            f"Вся требуемая для этапа «{rule.work_name}» техника обнаружена, "
            "неожиданной техники не найдено."
        )

    return StageEvaluation(
        stage_id=stage.stage_id,
        work_name=rule.work_name,
        zone_id=stage.zone_id,
        status=status,
        status_label_ru=STATUS_LABELS_RU[status],
        required=rule.required,
        allowed=rule.allowed,
        missing_required=missing_required,
        unexpected_detections=unexpected,
        ambiguous_detections=[d for group in ambiguous_by_class.values() for d in group],
        explanation_ru=explanation,
        evidence=evidence,
        quantity_checks=quantity_checks,
    )


def evaluate_observation(
    *,
    zone_id: str,
    observed_date: date | None,
    date_confirmed: bool,
    detections: list[Detection],
    schedule: Schedule,
    rules: EquipmentRules,
) -> ObservationEvaluation:
    if not date_confirmed or observed_date is None:
        return ObservationEvaluation(
            zone_id=zone_id,
            observed_date=observed_date,
            date_confirmed=False,
            overall_status=STATUS_INSUFFICIENT_DATA,
            overall_status_label_ru=STATUS_LABELS_RU[STATUS_INSUFFICIENT_DATA],
            overall_explanation_ru=(
                "Дата снимка не подтверждена, поэтому нельзя надёжно выбрать активный этап "
                "графика. Обнаруженная техника показана как справочная информация."
            ),
            stage_evaluations=[],
            all_detections=detections,
        )

    active_stages = schedule.active_stages(zone_id, observed_date)
    if not active_stages:
        return ObservationEvaluation(
            zone_id=zone_id,
            observed_date=observed_date,
            date_confirmed=True,
            overall_status=STATUS_INSUFFICIENT_DATA,
            overall_status_label_ru=STATUS_LABELS_RU[STATUS_INSUFFICIENT_DATA],
            overall_explanation_ru=(
                f"На {observed_date.isoformat()} в зоне «{zone_id}» по графику нет активного "
                "этапа — проверка по правилам техники невозможна."
            ),
            stage_evaluations=[],
            all_detections=detections,
        )

    zone_allowed = _zone_allowed_classes(active_stages, rules)
    stage_evaluations = []
    for stage in active_stages:
        rule = rules.stage_rules.get(stage.stage_id)
        if rule is None:
            stage_evaluations.append(
                StageEvaluation(
                    stage_id=stage.stage_id,
                    work_name=stage.work_name,
                    zone_id=stage.zone_id,
                    status=STATUS_INSUFFICIENT_DATA,
                    status_label_ru=STATUS_LABELS_RU[STATUS_INSUFFICIENT_DATA],
                    required=[],
                    allowed=[],
                    missing_required=[],
                    unexpected_detections=[],
                    ambiguous_detections=[],
                    explanation_ru=f"Для этапа «{stage.work_name}» не задано правило техники.",
                )
            )
            continue
        stage_evaluations.append(
            _evaluate_stage(stage, rule, detections, zone_allowed, rules.confusable_class_pairs)
        )

    priority = {STATUS_POSSIBLE_DEVIATION: 0, STATUS_INSUFFICIENT_DATA: 1, STATUS_NO_DEVIATION: 2}
    overall_status = min((e.status for e in stage_evaluations), key=lambda s: priority[s])

    return ObservationEvaluation(
        zone_id=zone_id,
        observed_date=observed_date,
        date_confirmed=True,
        overall_status=overall_status,
        overall_status_label_ru=STATUS_LABELS_RU[overall_status],
        overall_explanation_ru=(
            f"Активных этапов на дату: {len(active_stages)}. "
            f"Итоговый статус определён по наиболее значимому отклонению среди них."
        ),
        stage_evaluations=stage_evaluations,
        all_detections=detections,
    )
