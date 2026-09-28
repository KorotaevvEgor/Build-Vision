"""LLM-слой BuildVision.

Отвечает за три вещи, которых нет в детекторе и ядре сопоставления:
результирующий вывод по наблюдению на естественном языке, оценку стадии
и готовности объекта по самой фотографии, и генерацию отчёта о ходе работ.

Слой намеренно изолирован от Django ORM и от маршрутов FastAPI: на вход
подаются обычные структуры данных, на выход — результат с явным признаком
доступности. Это позволяет вызывать его из любого места и честно
деградировать, когда внешний API недоступен.
"""

from .client import LLMResult, llm_is_configured
from .conclusion import (
    ObservationSummary,
    StageFact,
    build_conclusion,
    build_photo_comment,
)
from .vision import STAGE_CATALOG, VisionAssessment, assess_photo

__all__ = [
    "STAGE_CATALOG",
    "LLMResult",
    "ObservationSummary",
    "StageFact",
    "VisionAssessment",
    "assess_photo",
    "build_conclusion",
    "build_photo_comment",
    "llm_is_configured",
]
