"""Пересечение почасового прогноза с этапами графика.

Механизм из плана: координаты → прогноз → пересечение с периодами работ →
настраиваемые погодные правила → перечень затронутых этапов и объяснение.
Вероятность осадков — не вероятность срыва сроков; результат — повод для
инженерной проверки, не автоматическая остановка работ (см. план).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .schedule import Schedule, Stage
from .weather import ForecastResult
from .weather_rules_config import WeatherRule


@dataclass(frozen=True)
class RiskPeriod:
    stage_id: str
    work_name: str
    factor: str
    comparison: str
    threshold: float
    units: str
    start_time_utc: str
    end_time_utc: str
    peak_value: float
    message: str


@dataclass(frozen=True)
class WeatherRiskReport:
    status: str  # "ok" | "unavailable"
    provider: str
    latitude: float
    longitude: float
    fetched_at: str | None
    is_stale: bool
    error: str | None
    risk_periods: list[RiskPeriod]


def _is_worse(comparison: str, candidate: float, current_best: float) -> bool:
    return candidate > current_best if comparison == "gte" else candidate < current_best


def evaluate_weather_risks(
    *,
    schedule: Schedule,
    weather_rules: list[WeatherRule],
    forecast: ForecastResult,
) -> WeatherRiskReport:
    if forecast.status != "ok" or not forecast.hourly:
        return WeatherRiskReport(
            status="unavailable",
            provider=forecast.provider,
            latitude=forecast.latitude,
            longitude=forecast.longitude,
            fetched_at=forecast.fetched_at.isoformat() if forecast.fetched_at else None,
            is_stale=True,
            error=forecast.error,
            risk_periods=[],
        )

    risk_periods: list[RiskPeriod] = []

    def flush_run(run: list[tuple[str, float]], rule: WeatherRule, stage: Stage) -> None:
        if not run:
            return
        peak = run[0][1]
        for _, value in run:
            if _is_worse(rule.comparison, value, peak):
                peak = value
        risk_periods.append(
            RiskPeriod(
                stage_id=stage.stage_id,
                work_name=stage.work_name,
                factor=rule.factor,
                comparison=rule.comparison,
                threshold=rule.threshold,
                units=rule.units,
                start_time_utc=run[0][0],
                end_time_utc=run[-1][0],
                peak_value=peak,
                message=rule.message,
            )
        )

    for rule in weather_rules:
        stage = schedule.by_id(rule.stage_id)
        if stage is None:
            continue

        violating_run: list[tuple[str, float]] = []
        for point in forecast.hourly:
            point_date = datetime.fromisoformat(point.time_utc).replace(tzinfo=timezone.utc).date()
            is_active = stage.start_date <= point_date <= stage.end_date
            value = point.value_of(rule.factor)

            if is_active and rule.violated_by(value):
                violating_run.append((point.time_utc, value))
            else:
                flush_run(violating_run, rule, stage)
                violating_run = []
        flush_run(violating_run, rule, stage)

    return WeatherRiskReport(
        status="ok",
        provider=forecast.provider,
        latitude=forecast.latitude,
        longitude=forecast.longitude,
        fetched_at=forecast.fetched_at.isoformat() if forecast.fetched_at else None,
        is_stale=forecast.is_stale,
        error=None,
        risk_periods=risk_periods,
    )
