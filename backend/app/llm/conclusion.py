"""Результирующий вывод по наблюдению на естественном языке.

Постановщики задачи сформулировали это требование дословно так: решение
должно выводить результирующий вывод, в том числе на основе языковых
моделей, над календарно-сетевым графиком, где есть план и факт.

Модуль не принимает решений: статусы и отклонения уже посчитаны ядром
сопоставления. Задача языковой модели — связать разрозненные факты в одно
объяснение для инженера и назвать причину, а не пересчитать их заново.
Поэтому на вход подаётся готовая структура, а промпт запрещает добавлять
факты, которых в ней нет.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from . import client

_SYSTEM_PROMPT = (
    "Ты инженер строительного контроля. По структурированным данным проверки "
    "снимка строительной площадки ты пишешь краткое заключение для "
    "руководителя проекта на русском языке.\n\n"
    "Жёсткие правила:\n"
    "1. Используй только факты из переданных данных. Не добавляй ничего от себя: "
    "ни количества техники, ни сроков, ни причин, которых нет во входных данных.\n"
    "2. Если данных недостаточно для вывода, прямо так и напиши.\n"
    "3. Не предлагай организационных мер, которые невозможно проверить по снимку.\n"
    "4. Обязательно назови причинно-следственную связь: что наблюдается, "
    "чему это противоречит по графику и чем это грозит сроку.\n"
    "5. Если в данных есть погодное ограничение, объясняющее отсутствие работ, "
    "укажи его как вероятную причину, а не как нарушение подрядчика.\n"
    "6. Если у этапа is_on_critical_path равно true, отдельно укажи, что он лежит на "
    "критическом пути и задержка по нему сдвигает срок сдачи объекта. Если false — "
    "не приписывай отклонению влияния на срок сдачи.\n"
    "7. Без вводных фраз и без markdown-заголовков. Три-пять предложений "
    "связным текстом."
)


@dataclass
class StageFact:
    """План и факт по одному этапу графика на дату наблюдения."""

    work_name: str
    start_date: str
    end_date: str
    status_label: str
    required_equipment: dict[str, int] = field(default_factory=dict)
    actual_equipment: dict[str, int] = field(default_factory=dict)
    missing_equipment: list[str] = field(default_factory=list)
    unexpected_equipment: list[str] = field(default_factory=list)
    ambiguous_equipment: list[str] = field(default_factory=list)
    is_on_critical_path: bool = False


@dataclass
class ObservationSummary:
    """Полный срез наблюдения, из которого строится заключение."""

    zone_name: str
    observed_date: str | None
    date_confirmed: bool
    overall_status_label: str
    stages: list[StageFact] = field(default_factory=list)
    idle_equipment: list[str] = field(default_factory=list)
    equipment_out_of_zone: list[str] = field(default_factory=list)
    equipment_in_danger_zone: list[str] = field(default_factory=list)
    uncovered_zones: list[str] = field(default_factory=list)
    weather_notes: list[str] = field(default_factory=list)
    vision_stage_label: str | None = None
    vision_readiness_percent: int | None = None
    schedule_stage_mismatch: bool = False


def _payload_digest(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_PHOTO_COMMENT_PROMPT = (
    "Ты инженер строительного контроля. По данным разбора одной фотографии "
    "строительной площадки напиши короткий комментарий на русском языке.\n\n"
    "Жёсткие правила:\n"
    "1. Календарного графика для этого снимка нет. Не делай выводов об отставании "
    "или опережении сроков — сравнивать не с чем.\n"
    "2. Используй только переданные данные: стадию, готовность, видимые признаки и "
    "состав обнаруженной техники. Ничего не добавляй от себя.\n"
    "3. Если состав техники не соответствует названной стадии, скажи об этом прямо.\n"
    "4. Без вводных фраз и без markdown. Два-три предложения."
)


def build_photo_comment(payload: dict, *, use_cache: bool = True) -> client.LLMResult:
    """Короткий комментарий по одиночному снимку без привязки к графику.

    Используется на публичном демонстрационном экране, где графика работ нет в
    принципе. Промпт отдельный именно поэтому: заключение по наблюдению обязано
    говорить о сроках, а здесь любой вывод о сроках был бы выдумкой.
    """
    messages = [
        {"role": "system", "content": _PHOTO_COMMENT_PROMPT},
        {
            "role": "user",
            "content": (
                "Разбор снимка:\n"
                f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
                "Напиши комментарий."
            ),
        },
    ]
    return client.chat(
        messages,
        cache_key=f"photo-comment|{_payload_digest(payload)}",
        max_tokens=400,
        use_cache=use_cache,
    )


def build_conclusion(summary: ObservationSummary, *, use_cache: bool = True) -> client.LLMResult:
    """Формирует текстовое заключение по наблюдению.

    При недоступной модели возвращает результат с ``available=False`` —
    интерфейс в этом случае показывает штатное объяснение ядра сопоставления
    и честную пометку, что заключение не сформировано.
    """
    payload = asdict(summary)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Данные проверки снимка:\n"
                f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
                "Напиши заключение для руководителя проекта."
            ),
        },
    ]
    return client.chat(
        messages,
        cache_key=f"conclusion|{_payload_digest(payload)}",
        max_tokens=700,
        use_cache=use_cache,
    )
