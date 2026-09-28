"""Настройки, которые пользователь меняет на ходу, без перезапуска сервиса.

Пороги уверенности живут в базе, а не в переменных окружения, по той же
причине, что и правила этапов: инженер должен иметь возможность подкрутить
чувствительность прямо во время работы и сразу увидеть результат на снимке.

Значения читаются на каждый вызов. Это один короткий запрос к БД, зато
изменение в интерфейсе или в админке применяется к следующему же анализу.
При недоступной базе возвращаются значения по умолчанию из config.py —
анализ снимка не должен падать из-за настроек.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import config, django_bridge

logger = logging.getLogger(__name__)

VLM_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class RuntimeSettings:
    detector_confidence: float
    autolabel_min_vlm_confidence: str
    ambiguity_margin: float
    from_database: bool


def load() -> RuntimeSettings:
    defaults = RuntimeSettings(
        detector_confidence=config.DEFAULT_CONF,
        autolabel_min_vlm_confidence="high",
        ambiguity_margin=0.15,
        from_database=False,
    )
    if not django_bridge.ensure_django_ready():
        return defaults

    try:
        from core.models import MatchingSettings

        row = MatchingSettings.objects.first()
    except Exception:
        logger.exception("Не удалось прочитать настройки, используются значения по умолчанию")
        return defaults

    if row is None:
        return defaults

    return RuntimeSettings(
        detector_confidence=float(row.detector_confidence),
        autolabel_min_vlm_confidence=row.autolabel_min_vlm_confidence,
        ambiguity_margin=float(row.ambiguity_margin),
        from_database=True,
    )


def accepts_vlm_confidence(reported: str, minimum: str) -> bool:
    """Проходит ли уверенность модели заданный пользователем минимум."""
    return VLM_CONFIDENCE_ORDER.get(reported, -1) >= VLM_CONFIDENCE_ORDER.get(minimum, 2)
