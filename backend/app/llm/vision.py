"""Оценка стадии строительства и готовности объекта по самой фотографии.

Зачем это нужно отдельно от детектора. Детектор отвечает на вопрос «какая
техника в кадре», но не видит самого объекта: на снимке почти достроенного
дома техники может не быть вовсе, и по составу техники стадию не определить.
Постановщики задачи назвали оценку стадии по фотографии «пунктом 1»
выполнения задачи и отдельно подтвердили сценарий «здание готово на 70%».

Результат этого модуля — второй, независимый от детектора источник истины.
Расхождение между ним, составом техники и календарным графиком само по себе
является отклонением уровня проекта: если модель видит фасадные работы, а в
графике на эту дату стоит устройство котлована, это надо показать инженеру.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StageDefinition:
    """Стадия строительства, сшитая с кодами справочника видов работ заказчика."""

    key: str
    label_ru: str
    work_codes: tuple[str, ...]


# Семь стадий, различимых на снимке снаружи. Внутренние отделочные работы
# сознательно не включены: по внешнему обзору они неотличимы, и постановщики
# подтвердили, что ограничиться внешней аналитикой допустимо.
STAGE_CATALOG: tuple[StageDefinition, ...] = (
    StageDefinition("site_preparation", "Подготовка территории и снос", ("10.3", "10.4")),
    StageDefinition("excavation", "Устройство котлована и земляные работы", ("12.3.1", "12.3.7")),
    StageDefinition("piling", "Свайные работы и ограждающие конструкции", ("12.3.2", "12.3.5")),
    StageDefinition("substructure", "Монолитные работы ниже отметки 0", ("12.3.9",)),
    StageDefinition("superstructure", "Монолитные работы выше отметки 0", ("12.4.28", "12.4.29")),
    StageDefinition("facade_roof", "Фасад и кровля", ("12.4.11", "12.4.31")),
    StageDefinition("landscaping", "Благоустройство и дорожные работы", ("12.7.1",)),
)

UNDETERMINED_KEY = "undetermined"
UNDETERMINED_LABEL = "Определить невозможно"

_LABEL_TO_KEY = {definition.label_ru: definition.key for definition in STAGE_CATALOG}
_LABEL_TO_KEY[UNDETERMINED_LABEL] = UNDETERMINED_KEY

_SYSTEM_PROMPT = (
    "Ты инженер строительного контроля. Ты анализируешь снимок строительной площадки "
    "и определяешь фактическую стадию работ. Отвечай строго одним JSON-объектом без "
    "текста вокруг него. Опирайся только на то, что реально видно на снимке. "
    "Если изображение не позволяет сделать вывод, честно выбирай стадию "
    f"«{UNDETERMINED_LABEL}» и ставь низкую уверенность. Не додумывай и не "
    "предполагай того, чего не видно."
)


def _build_user_prompt() -> str:
    stages = [definition.label_ru for definition in STAGE_CATALOG] + [UNDETERMINED_LABEL]
    return (
        "Определи по снимку строительной площадки:\n"
        f"1. stage — стадия строительства, строго одно значение из списка: "
        f"{json.dumps(stages, ensure_ascii=False)}\n"
        "2. readiness_percent — оценка готовности объекта в процентах, целое число от 0 до 100\n"
        "3. visual_evidence — массив из 2-5 строк: конкретные видимые признаки, "
        "на которых основан вывод о стадии\n"
        "4. equipment — массив строк: типы строительной техники, которые видно в кадре\n"
        "5. confidence — уверенность: high, medium или low\n"
        "6. date_stamp — дата в формате ДД.ММ.ГГГГ, если она впечатана в изображение, иначе null\n\n"
        "Верни только JSON с этими шестью ключами."
    )


@dataclass(frozen=True)
class VisionAssessment:
    """Оценка снимка. ``available=False`` — оценки нет, причина в ``error``."""

    available: bool
    stage_key: str = UNDETERMINED_KEY
    stage_label: str = UNDETERMINED_LABEL
    readiness_percent: int | None = None
    visual_evidence: list[str] = field(default_factory=list)
    equipment: list[str] = field(default_factory=list)
    confidence: str = "low"
    date_stamp: str | None = None
    cached: bool = False
    model: str = ""
    error: str | None = None


def _file_digest(image_path: Path) -> str:
    hasher = hashlib.sha256()
    with image_path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _coerce_percent(raw: object) -> int | None:
    """Приводит оценку готовности к целому 0-100, не выдумывая значение."""
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = round(float(raw))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, value))


def _coerce_str_list(raw: object, limit: int = 8) -> list[str]:
    if not isinstance(raw, list):
        return []
    items = [str(item).strip() for item in raw if str(item).strip()]
    return items[:limit]


def assess_photo(
    image_path: Path,
    *,
    image_sha256: str | None = None,
    use_cache: bool = True,
) -> VisionAssessment:
    """Определяет стадию, готовность и штамп даты по снимку.

    ``image_sha256`` можно передать, если хэш уже посчитан при загрузке файла —
    он служит ключом кэша, и второй раз читать мегабайты с диска незачем.
    """
    if not image_path.is_file():
        return VisionAssessment(available=False, error=f"файл не найден: {image_path}")

    digest = image_sha256 or _file_digest(image_path)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _build_user_prompt()},
                {"type": "image_url", "image_url": {"url": client.image_data_url(image_path)}},
            ],
        },
    ]

    result = client.chat(
        messages,
        cache_key=f"vision|{digest}",
        model=client.vision_model(),
        max_tokens=900,
        use_cache=use_cache,
    )
    if not result.available:
        return VisionAssessment(available=False, error=result.error)

    parsed = client.parse_json_response(result.text)
    if parsed is None:
        logger.warning("Модель вернула неразбираемый ответ для %s", image_path.name)
        return VisionAssessment(
            available=False,
            error="ответ модели не удалось разобрать как JSON",
            model=result.model,
        )

    stage_label = str(parsed.get("stage", "")).strip()
    stage_key = _LABEL_TO_KEY.get(stage_label)
    if stage_key is None:
        # Модель ответила стадией не из списка — не подгоняем под ближайшую,
        # а честно фиксируем неопределённость.
        logger.info("Стадия вне справочника: %r", stage_label)
        stage_key, stage_label = UNDETERMINED_KEY, UNDETERMINED_LABEL

    confidence = str(parsed.get("confidence", "low")).strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    date_stamp = parsed.get("date_stamp")
    date_stamp = str(date_stamp).strip() if date_stamp else None

    return VisionAssessment(
        available=True,
        stage_key=stage_key,
        stage_label=stage_label,
        readiness_percent=_coerce_percent(parsed.get("readiness_percent")),
        visual_evidence=_coerce_str_list(parsed.get("visual_evidence"), limit=5),
        equipment=_coerce_str_list(parsed.get("equipment")),
        confidence=confidence,
        date_stamp=date_stamp,
        cached=result.cached,
        model=result.model,
    )
