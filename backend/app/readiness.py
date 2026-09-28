"""Готовность объекта во времени: факт по фотографиям на фоне плана работ.

Самый наглядный ответ на вопрос «что происходит на объекте». Проценты
выполнения из отчётов подрядчика проверить нечем, а оценка готовности по
самой фотографии получена независимо и повторяется на каждом обходе.

Чего здесь намеренно нет — плановой кривой готовности. В материалах
заказчика её не существует, и нарисовать вторую линию «как должно быть»
означало бы выдать выдумку за норматив. Вместо этого план показан тем, чем
он реально является: полосами запланированных работ на той же оси времени.
Видно, какая работа должна идти сейчас, и что на снимках в это время.

Числовое отставание считается не здесь, а в расчёте критического пути, где
для него есть основание: сдвиг даты сдачи в днях.

Ещё одно ограничение: факт усредняется по обходу. В один день разные ракурсы
дают разные проценты, и рисовать их отдельными точками значило бы выдавать
разброс оценки за колебания стройки.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from . import django_bridge

logger = logging.getLogger(__name__)


def _fact_points(site) -> list[dict]:
    from core.models import Observation

    rows = (
        Observation.objects.filter(
            zone__site=site,
            date_confirmed=True,
            observed_date__isnull=False,
            readiness_percent__isnull=False,
        )
        .values("observed_date", "readiness_percent", "vision_stage_label")
        .order_by("observed_date")
    )

    by_session: dict[date, list[int]] = {}
    labels: dict[date, str] = {}
    for row in rows:
        by_session.setdefault(row["observed_date"], []).append(row["readiness_percent"])
        labels.setdefault(row["observed_date"], row["vision_stage_label"] or "")

    return [
        {
            "date": session.isoformat(),
            "readiness_percent": round(sum(values) / len(values)),
            "spread": max(values) - min(values),
            "frames": len(values),
            "stage_label": labels.get(session, ""),
        }
        for session, values in sorted(by_session.items())
    ]


def curve(site, today: date | None = None) -> dict:
    """Фактическая готовность во времени и плановые периоды работ."""
    if not django_bridge.ensure_django_ready():
        return {"available": False, "fact": [], "planned_stages": []}

    from core.models import Stage

    today = today or datetime.now(UTC).date()
    try:
        fact = _fact_points(site)
    except Exception:
        logger.exception("Не удалось собрать готовность объекта %s", site.pk)
        return {"available": False, "fact": [], "planned_stages": []}

    stages = list(
        Stage.objects.filter(zone__site=site)
        .order_by("start_date")
        .values("external_id", "work_name", "start_date", "end_date")
    )
    planned = [
        {
            "stage_id": stage["external_id"],
            "work_name": stage["work_name"],
            "start_date": stage["start_date"].isoformat(),
            "end_date": stage["end_date"].isoformat(),
            "is_current": stage["start_date"] <= today <= stage["end_date"],
        }
        for stage in stages
    ]

    current_plan = next((item for item in planned if item["is_current"]), None)
    last_seen = fact[-1] if fact else None

    # Расхождение формулируется словами и только когда есть обе стороны сравнения.
    # «Не видно» и «видно другое» — разные утверждения, и путать их нельзя.
    if current_plan is None:
        mismatch = None
    elif last_seen is None:
        mismatch = {
            "kind": "no_evidence",
            "message": (
                f"По графику сейчас идёт «{current_plan['work_name']}», но подтверждённых "
                "снимков с оценкой готовности по объекту нет — сверить не с чем."
            ),
        }
    elif last_seen["stage_label"] and last_seen["stage_label"] not in current_plan["work_name"]:
        mismatch = {
            "kind": "stage_mismatch",
            "message": (
                f"По графику сейчас идёт «{current_plan['work_name']}», а на последнем снимке "
                f"от {last_seen['date']} видна стадия «{last_seen['stage_label']}»."
            ),
        }
    else:
        mismatch = {
            "kind": "match",
            "message": (
                f"Стадия на последнем снимке совпадает с работой графика "
                f"«{current_plan['work_name']}»."
            ),
        }

    return {
        "available": bool(fact),
        "today": today.isoformat(),
        "fact": fact,
        "planned_stages": planned,
        "current_planned_work": current_plan["work_name"] if current_plan else None,
        "last_observed_stage": last_seen["stage_label"] if last_seen else None,
        "mismatch": mismatch,
        "method_note": (
            "Точка кривой — оценка готовности по фотографиям одного обхода, усреднённая по "
            "ракурсам. Плановой кривой готовности в материалах заказчика нет, поэтому вторая "
            "линия не рисуется: план показан полосами запланированных работ. Отставание в днях "
            "считается по критическому пути и показано в карточке срока сдачи."
        ),
    }
