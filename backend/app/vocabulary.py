"""Словарь открытой детекции.

Основной источник — таблица core.VocabularyClass в PostgreSQL (редактируется через
 Django admin). Если БД временно недоступна — резервный откат на data/config/vocabulary.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from . import django_bridge
from .config import VOCABULARY_PATH


@dataclass(frozen=True)
class ClassInfo:
    key: str
    label_ru: str
    in_taxonomy: bool


@dataclass(frozen=True)
class Vocabulary:
    prompts: list[str]
    prompt_to_class: dict[str, ClassInfo]
    classes: dict[str, ClassInfo]

    def class_for_prompt(self, prompt: str) -> ClassInfo:
        return self.prompt_to_class[prompt]


def _load_vocabulary_from_file(path: Path = VOCABULARY_PATH) -> Vocabulary:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    prompts: list[str] = []
    prompt_to_class: dict[str, ClassInfo] = {}
    classes: dict[str, ClassInfo] = {}

    for group_name, in_taxonomy in (("classes", True), ("distractors", False)):
        for entry in data.get(group_name) or []:
            info = ClassInfo(key=entry["key"], label_ru=entry["label_ru"], in_taxonomy=in_taxonomy)
            classes[info.key] = info
            for prompt in entry["prompts"]:
                prompts.append(prompt)
                prompt_to_class[prompt] = info

    return Vocabulary(prompts=prompts, prompt_to_class=prompt_to_class, classes=classes)


def _load_vocabulary_from_db() -> Vocabulary:
    from core.models import VocabularyClass

    prompts: list[str] = []
    prompt_to_class: dict[str, ClassInfo] = {}
    classes: dict[str, ClassInfo] = {}

    for row in VocabularyClass.objects.all():
        info = ClassInfo(key=row.key, label_ru=row.label_ru, in_taxonomy=row.in_taxonomy)
        classes[info.key] = info
        for prompt in row.prompts:
            prompts.append(prompt)
            prompt_to_class[prompt] = info

    if not classes:
        raise ValueError("Словарь классов в БД пуст — выполните `python manage.py seed_demo_data`")

    return Vocabulary(prompts=prompts, prompt_to_class=prompt_to_class, classes=classes)


def load_vocabulary(path: Path = VOCABULARY_PATH) -> Vocabulary:
    if django_bridge.ensure_django_ready():
        try:
            return _load_vocabulary_from_db()
        except Exception:
            django_bridge.logger.exception("Не удалось загрузить словарь из БД, откат на файл")
    return _load_vocabulary_from_file(path)
