"""Расчётный движок прогноза сроков — без ML-предсказания и без LLM.

См. план, модуль «Прогноз сроков»:
  * «% выполнения»/темп — не физический прогресс, а честная эвристика:
    доля подтверждённых наблюдений зоны за период этапа со статусом
    `no_deviation`. Документируется как эвристика, а не точный факт.
  * Погода учитывается только в реальном горизонте прогноза Open-Meteo
    (~72ч, см. weather.py) — для более далёких дат риск не выдумывается.
  * Объяснение риска — шаблонный текст на структурированных данных, без
    LLM-зависимости (см. план, раздел «Авторизация»/«Прогноз сроков»).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from . import django_bridge
from .schedule import Schedule, Stage
from .weather import fetch_forecast
from .weather_matching import evaluate_weather_risks
from .weather_rules_config import WeatherRule


@dataclass(frozen=True)
class RiskFactor:
    key: str
    severity: str  # "high" | "medium" | "low"
    message: str


def _stage_observations(zone_id: str, stage: Stage, today: date, site=None) -> list:
    """Подтверждённые наблюдения зоны за период этапа (от начала до сегодня/конца)."""
    if not django_bridge.ensure_django_ready():
        return []
    from core.models import Observation

    window_end = min(today, stage.end_date)
    site_filter = {"zone__site": site} if site is not None else {"zone__site__is_legacy": True}
    qs = Observation.objects.filter(
        zone__external_id=zone_id,
        observed_date__gte=stage.start_date,
        observed_date__lte=window_end,
        date_confirmed=True,
        **site_filter,
    )
    return list(qs.order_by("observed_date"))


def _compliance_rate(observations: list) -> float | None:
    if not observations:
        return None
    compliant = sum(1 for o in observations if o.overall_status == "no_deviation")
    return compliant / len(observations)


def _latest_quantity_shortfalls(observations: list, stage_id: str) -> list[dict]:
    if not observations or not django_bridge.ensure_django_ready():
        return []
    from core.models import StageEvaluationRecord

    latest = observations[-1]
    stage_eval = (
        StageEvaluationRecord.objects.filter(observation=latest, stage__external_id=stage_id).first()
    )
    if not stage_eval:
        return []
    return [c for c in stage_eval.quantity_checks_snapshot if not c.get("satisfied", True)]


def forecast_for_stage(
    *,
    stage: Stage,
    schedule: Schedule,
    weather_rules: list[WeatherRule],
    latitude: float,
    longitude: float,
    today: date,
    site=None,
) -> dict:
    observations = _stage_observations(stage.zone_id, stage, today, site=site)
    average_compliance = _compliance_rate(observations)
    current_compliance = _compliance_rate(observations[-3:])

    planned_days = (stage.end_date - stage.start_date).days + 1
    projected_end = stage.end_date
    delay_days = 0
    if average_compliance is not None and average_compliance > 0:
        delay_days = max(0, round(planned_days * (1 / average_compliance - 1)))
        projected_end = stage.end_date + timedelta(days=delay_days)
    elif average_compliance == 0:
        # Честно грубая оценка при нулевом наблюдаемом темпе — не точный расчёт,
        # а сигнал "как минимум весь период заново", помеченный явным риском ниже.
        delay_days = planned_days
        projected_end = stage.end_date + timedelta(days=delay_days)

    factors: list[RiskFactor] = []

    shortfalls = _latest_quantity_shortfalls(observations, stage.stage_id)
    if shortfalls:
        names = ", ".join(
            f"{c['label_ru']} (план {c['required_qty']}, факт {c['actual_qty']})" for c in shortfalls
        )
        factors.append(RiskFactor("missing_equipment", "high", f"Нехватка техники: {names}"))

    if average_compliance is None:
        factors.append(
            RiskFactor(
                "insufficient_data",
                "low",
                "Недостаточно подтверждённых наблюдений по этапу, чтобы надёжно оценить темп.",
            )
        )
    elif current_compliance is not None and current_compliance < average_compliance:
        factors.append(
            RiskFactor(
                "pace_decline",
                "medium",
                f"Текущий темп ({current_compliance * 100:.0f}% наблюдений без отклонений) ниже "
                f"среднего по этапу ({average_compliance * 100:.0f}%).",
            )
        )

    weather_forecast = fetch_forecast(latitude, longitude)
    weather_report = evaluate_weather_risks(schedule=schedule, weather_rules=weather_rules, forecast=weather_forecast)
    for period in weather_report.risk_periods:
        if period.stage_id == stage.stage_id:
            factors.append(RiskFactor("weather", "medium", period.message))

    deviation_count = sum(1 for o in observations if o.overall_status == "possible_deviation")
    if deviation_count >= 2:
        factors.append(
            RiskFactor(
                "deviation_history", "medium", f"Зафиксировано {deviation_count} отклонений за период этапа."
            )
        )

    severity_order = {"high": 0, "medium": 1, "low": 2}
    factors.sort(key=lambda f: severity_order[f.severity])

    return {
        "stage_id": stage.stage_id,
        "work_name": stage.work_name,
        "zone_id": stage.zone_id,
        "planned_start_date": stage.start_date.isoformat(),
        "planned_days": planned_days,
        "planned_end_date": stage.end_date.isoformat(),
        "projected_end_date": projected_end.isoformat(),
        "delay_days": delay_days,
        "average_compliance_percent": round(average_compliance * 100, 1) if average_compliance is not None else None,
        "current_compliance_percent": round(current_compliance * 100, 1) if current_compliance is not None else None,
        "observation_count": len(observations),
        "risk_factors": [{"key": f.key, "severity": f.severity, "message": f.message} for f in factors],
    }
