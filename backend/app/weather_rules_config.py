"""Погодные правила.

Основной источник — таблица core.WeatherRule в PostgreSQL (редактируется
через Django admin). Резервный откат при недоступности БД —
data/config/weather_rules.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from . import django_bridge
from .config import WEATHER_RULES_PATH


@dataclass(frozen=True)
class WeatherRule:
    stage_id: str
    factor: str
    comparison: str  # "gte" | "lte"
    threshold: float
    units: str
    message: str

    def violated_by(self, value: float | None) -> bool:
        if value is None:
            return False
        if self.comparison == "gte":
            return value >= self.threshold
        if self.comparison == "lte":
            return value <= self.threshold
        raise ValueError(f"Неизвестный тип сравнения: {self.comparison}")


def _load_weather_rules_from_file(path: Path = WEATHER_RULES_PATH) -> list[WeatherRule]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        WeatherRule(
            stage_id=entry["stage_id"],
            factor=entry["factor"],
            comparison=entry["comparison"],
            threshold=float(entry["threshold"]),
            units=entry.get("units", ""),
            message=(entry.get("message") or "").strip(),
        )
        for entry in data.get("rules") or []
    ]


def _load_weather_rules_from_db(site=None) -> list[WeatherRule]:
    from core.models import WeatherRule as WeatherRuleRow

    qs = WeatherRuleRow.objects.select_related("stage")
    qs = qs.filter(stage__zone__site=site) if site is not None else qs.filter(stage__zone__site__is_legacy=True)
    return [
        WeatherRule(
            stage_id=row.stage.external_id,
            factor=row.factor,
            comparison=row.comparison,
            threshold=row.threshold,
            units=row.units,
            message=row.message,
        )
        for row in qs
    ]


def load_weather_rules(path: Path = WEATHER_RULES_PATH, site=None) -> list[WeatherRule]:
    if django_bridge.ensure_django_ready():
        try:
            return _load_weather_rules_from_db(site=site)
        except Exception:
            if site is not None:
                raise
            django_bridge.logger.exception("Не удалось загрузить погодные правила из БД, откат на файл")
    elif site is not None:
        from fastapi import HTTPException

        raise HTTPException(503, "База данных недоступна")
    return _load_weather_rules_from_file(path)
