"""Тесты погодного модуля: пересечение прогноза с этапами, честная деградация.

Сеть не используется — прогноз конструируется вручную, чтобы тесты были
быстрыми и детерминированными (см. план: тесты не зависят от live-API).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.schedule import Schedule, Stage
from app.weather import ForecastResult, HourlyPoint
from app.weather_matching import evaluate_weather_risks
from app.weather_rules_config import WeatherRule


def make_schedule() -> Schedule:
    return Schedule(
        is_demo=True,
        stages=[
            Stage(
                stage_id="stage-kotlovan",
                work_code="12.3.1.",
                work_name="Устройство котлована",
                zone_id="zone-a",
                start_date=date(2026, 9, 10),
                end_date=date(2026, 9, 22),
                technology_assumption="",
                is_demo=True,
            )
        ],
    )


def make_forecast(points: list[HourlyPoint], status: str = "ok") -> ForecastResult:
    return ForecastResult(
        status=status,
        provider="open-meteo",
        latitude=55.75,
        longitude=37.6,
        fetched_at=datetime.now(timezone.utc) if status == "ok" else None,
        hourly=points,
    )


def hourly(hour_iso: str, precipitation_probability: float | None) -> HourlyPoint:
    return HourlyPoint(
        time_utc=hour_iso,
        temperature_2m=15.0,
        precipitation=0.0,
        precipitation_probability=precipitation_probability,
        wind_speed_10m=5.0,
        wind_gusts_10m=8.0,
    )


RULE = WeatherRule(
    stage_id="stage-kotlovan",
    factor="precipitation_probability",
    comparison="gte",
    threshold=60,
    units="%",
    message="осадки выше порога",
)


def test_risk_period_detected_when_threshold_exceeded() -> None:
    schedule = make_schedule()
    forecast = make_forecast(
        [
            hourly("2026-09-15T10:00", 20),
            hourly("2026-09-15T11:00", 70),
            hourly("2026-09-15T12:00", 80),
            hourly("2026-09-15T13:00", 30),
        ]
    )
    report = evaluate_weather_risks(schedule=schedule, weather_rules=[RULE], forecast=forecast)

    assert report.status == "ok"
    assert len(report.risk_periods) == 1
    period = report.risk_periods[0]
    assert period.start_time_utc == "2026-09-15T11:00"
    assert period.end_time_utc == "2026-09-15T12:00"
    assert period.peak_value == 80


def test_no_risk_period_outside_active_stage_dates() -> None:
    schedule = make_schedule()
    # Дата вне периода этапа (10-22 сентября) — риск не должен считаться,
    # даже если порог превышен.
    forecast = make_forecast([hourly("2026-10-01T10:00", 90)])
    report = evaluate_weather_risks(schedule=schedule, weather_rules=[RULE], forecast=forecast)
    assert report.risk_periods == []


def test_unavailable_forecast_does_not_report_no_risk_silently() -> None:
    schedule = make_schedule()
    forecast = ForecastResult(
        status="unavailable",
        provider="open-meteo",
        latitude=55.75,
        longitude=37.6,
        fetched_at=None,
        hourly=[],
        error="timeout",
    )
    report = evaluate_weather_risks(schedule=schedule, weather_rules=[RULE], forecast=forecast)
    assert report.status == "unavailable"
    assert report.risk_periods == []


def test_below_threshold_produces_no_risk_period() -> None:
    schedule = make_schedule()
    forecast = make_forecast([hourly("2026-09-15T10:00", 10), hourly("2026-09-15T11:00", 5)])
    report = evaluate_weather_risks(schedule=schedule, weather_rules=[RULE], forecast=forecast)
    assert report.risk_periods == []
