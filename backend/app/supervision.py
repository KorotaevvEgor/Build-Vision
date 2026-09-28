"""Участок надзора: все объекты инспектора на одном экране.

Зачем отдельный модуль. Всё остальное в системе смотрит внутрь одного
проекта, а у сотрудника надзорного органа объектов десятки, и его рабочий
день начинается не с объекта, а с вопроса «где сегодня плохо». Ответ на этот
вопрос нельзя собрать из проектных эндпоинтов, не сделав по запросу на
объект, поэтому он считается здесь одним проходом.

Главная величина экрана — не количество снимков, а количество карточек,
требующих решения человека. Смысл системы в том, чтобы это число было
маленьким при большом числе обработанных кадров.

Отдельно считается то, что обычно теряется: объекты, по которым давно не было
подтверждённых снимков. Отсутствие отклонений по такому объекту не означает,
что там всё хорошо, — оно означает, что там ничего не проверяли.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from . import django_bridge, schedule_network
from .schedule import load_schedule

logger = logging.getLogger(__name__)

#: Через сколько дней без подтверждённого снимка объект считается непроверенным.
#: Камеры снимают ежедневно, обходы — раз в месяц; две недели молчания это уже
#: потеря контроля, но ещё не повод для тревоги при месячном цикле съёмки.
STALE_AFTER_DAYS = 30


def _accessible_sites(user_id: int, is_admin: bool):
    from core.models import ConstructionSite

    if is_admin:
        return ConstructionSite.objects.all()
    return ConstructionSite.objects.filter(memberships__user_id=user_id)


def _object_row(site, today: date) -> dict:
    from core.models import Deviation, Observation

    observations = Observation.objects.filter(zone__site=site)
    dated = observations.filter(date_confirmed=True, observed_date__isnull=False)
    latest = dated.order_by("-observed_date").first()
    latest_any = observations.order_by("-created_at").first()

    deviations = Deviation.objects.filter(zone__site=site)
    open_deviations = deviations.filter(status__in=Deviation.OPEN_STATUSES)

    days_since = (today - latest.observed_date).days if latest else None

    # Готовность берём из последнего снимка, где модель смогла её оценить.
    # Последний снимок вообще может быть без оценки — тогда честнее показать
    # более ранний результат, чем пустое место.
    with_readiness = dated.filter(readiness_percent__isnull=False).order_by("-observed_date").first()

    row = {
        "project_id": site.pk,
        "name": site.name,
        "address": site.address,
        "is_demo": site.is_demo,
        "observation_count": observations.count(),
        "dated_observation_count": dated.count(),
        "last_observation_date": latest.observed_date.isoformat() if latest else None,
        "days_since_last_observation": days_since,
        "has_confirmed_dates": latest is not None,
        "is_stale": days_since is None or days_since > STALE_AFTER_DAYS,
        "stage_label": with_readiness.vision_stage_label if with_readiness else "",
        "readiness_percent": with_readiness.readiness_percent if with_readiness else None,
        "readiness_date": (
            with_readiness.observed_date.isoformat() if with_readiness else None
        ),
        "open_deviations": open_deviations.count(),
        "critical_deviations": open_deviations.filter(severity="critical").count(),
        "on_critical_path_deviations": open_deviations.filter(is_on_critical_path=True).count(),
        "resolved_awaiting_confirmation": deviations.filter(
            status=Deviation.Status.RESOLVED
        ).count(),
        "latest_observation_id": str(latest_any.id) if latest_any else None,
        "schedule_status": "unknown",
        "schedule_status_label_ru": "График не задан",
        "shift_days": 0,
        "planned_finish_date": None,
        "projected_finish_date": None,
    }

    try:
        schedule = load_schedule(site=site)
    except Exception:
        logger.exception("Не удалось загрузить график объекта %s", site.pk)
        return row

    if not schedule.stages:
        return row

    report = schedule_network.build_report(schedule, today, site=site)
    if not report.available:
        row["schedule_status_label_ru"] = report.reason
        return row

    row.update(
        {
            "schedule_status": report.status,
            "schedule_status_label_ru": schedule_network.PROJECT_STATUS_LABELS[report.status],
            "shift_days": report.shift_days,
            "planned_finish_date": (
                report.baseline_finish.isoformat() if report.baseline_finish else None
            ),
            "projected_finish_date": (
                report.projected_finish.isoformat() if report.projected_finish else None
            ),
        }
    )

    active = [
        stage
        for stage in report.stages
        if not stage["is_summary"] and stage["state"] == schedule_network.IN_PROGRESS
    ]
    if active:
        row["current_work_name"] = active[0]["work_name"]
        row["current_work_is_critical"] = active[0]["is_critical"]
    else:
        row["current_work_name"] = None
        row["current_work_is_critical"] = False

    return row


def review_queue(*, user_id: int, is_admin: bool, limit: int = 40) -> dict:
    """Очередь разбора: что именно инспектору надо решить сегодня.

    Порядок сортировки — это и есть главная ценность экрана, поэтому он задан
    явно и объяснимо: сначала то, что двигает дату сдачи (критический путь),
    затем по важности, затем повторяющееся выше разового, и только потом
    свежее выше старого. Сортировка только по дате заставляла бы инспектора
    разгребать мелочь перед тем, как добраться до срыва срока.
    """
    if not django_bridge.ensure_django_ready():
        return {"available": False, "items": [], "total": 0}

    from core.models import Deviation

    site_ids = list(_accessible_sites(user_id, is_admin).values_list("pk", flat=True))
    queryset = (
        Deviation.objects.filter(
            zone__site_id__in=site_ids, status__in=Deviation.OPEN_STATUSES
        )
        .select_related("zone", "zone__site", "stage", "first_observation", "assignee")
    )

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    items = sorted(
        queryset,
        key=lambda item: (
            not item.is_on_critical_path,
            severity_order.get(item.severity, 3),
            -item.occurrence_count,
            -item.detected_at.timestamp(),
        ),
    )
    total = len(items)

    return {
        "available": True,
        "total": total,
        "items": [
            {
                "id": item.pk,
                "project_id": item.zone.site_id,
                "project_name": item.zone.site.name,
                "zone_name": item.zone.name,
                "kind": item.kind,
                "kind_label_ru": item.get_kind_display(),
                "severity": item.severity,
                "severity_label_ru": item.get_severity_display(),
                "status": item.status,
                "status_label_ru": item.get_status_display(),
                "title": item.title,
                "message": item.message,
                "equipment": item.equipment,
                "work_name": item.stage.work_name if item.stage else None,
                "is_on_critical_path": item.is_on_critical_path,
                "occurrence_count": item.occurrence_count,
                "assignee": (
                    item.assignee.get_full_name() or item.assignee.username
                    if item.assignee
                    else None
                ),
                "observation_id": (
                    str(item.first_observation_id) if item.first_observation_id else None
                ),
                "observed_date": (
                    item.first_observation.observed_date.isoformat()
                    if item.first_observation and item.first_observation.observed_date
                    else None
                ),
                "detected_at": item.detected_at.isoformat(),
            }
            for item in items[:limit]
        ],
    }


def portfolio(*, user_id: int, is_admin: bool) -> dict:
    """Сводка по всем доступным пользователю объектам."""
    if not django_bridge.ensure_django_ready():
        return {"available": False, "objects": [], "totals": {}}

    from core.models import Deviation, Observation

    today = datetime.now(UTC).date()
    sites = list(_accessible_sites(user_id, is_admin).order_by("name"))
    rows = [_object_row(site, today) for site in sites]

    site_ids = [site.pk for site in sites]
    observations = Observation.objects.filter(zone__site_id__in=site_ids)
    deviations = Deviation.objects.filter(zone__site_id__in=site_ids)
    open_deviations = deviations.filter(status__in=Deviation.OPEN_STATUSES)

    recent_since = today - timedelta(days=30)
    behind = [row for row in rows if row["schedule_status"] == "behind"]
    stale = [row for row in rows if row["is_stale"]]

    return {
        "available": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "stale_after_days": STALE_AFTER_DAYS,
        "totals": {
            "objects": len(rows),
            "observations_total": observations.count(),
            "observations_last_30_days": observations.filter(
                observed_date__gte=recent_since
            ).count(),
            # Главное число экрана: сколько карточек ждёт решения человека.
            "requires_decision": open_deviations.count(),
            "critical": open_deviations.filter(severity="critical").count(),
            "awaiting_confirmation": deviations.filter(
                status=Deviation.Status.RESOLVED
            ).count(),
            "objects_behind": len(behind),
            "objects_stale": len(stale),
        },
        "objects": rows,
        "stale_objects": [
            {
                "project_id": row["project_id"],
                "name": row["name"],
                "days_since_last_observation": row["days_since_last_observation"],
                "has_confirmed_dates": row["has_confirmed_dates"],
            }
            for row in stale
        ],
    }
