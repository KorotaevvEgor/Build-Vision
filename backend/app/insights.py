"""Агрегации для Главной, Камер, Аналитики и Уведомлений.

В отличие от schedule.py/rules_config.py (у которых есть файловый откат),
у этих данных нет файлового источника — это история реальных наблюдений и
камеры, полностью производные от PostgreSQL (Observation/Detection/Camera).
Если БД недоступна, функции возвращают честный пустой результат с флагом
``available: False``, а не выдумывают цифры.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from . import django_bridge
from .forecast import forecast_for_stage
from .schedule import Schedule, Stage
from .weather_rules_config import WeatherRule


def db_available() -> bool:
    return django_bridge.ensure_django_ready()


def _observation_summary(obs) -> dict:
    return {
        "observation_id": str(obs.id),
        "overall_status": obs.overall_status,
        "overall_status_label_ru": obs.get_overall_status_display(),
        "created_at": obs.created_at.isoformat(),
        "observed_date": obs.observed_date.isoformat() if obs.observed_date else None,
        "image_path": obs.image_path,
    }


def _site_filter_kwargs(site) -> dict:
    """``site=None`` означает legacy-проект (единообразно с schedule.py/rules_config.py/
    weather_rules_config.py), а не «без фильтра» — иначе legacy `/api/...` эндпоинты
    показывали бы данные всех проектов."""
    return {"zone__site": site} if site is not None else {"zone__site__is_legacy": True}


def _latest_observation_for_zone(zone_external_id: str, site=None):
    from core.models import Observation

    qs = Observation.objects.filter(zone__external_id=zone_external_id, **_site_filter_kwargs(site))
    return qs.order_by("-created_at").first()


def _detected_classes(obs) -> list[str]:
    if obs is None:
        return []
    return sorted(
        {d.class_key for d in obs.detections.all() if d.in_taxonomy and not d.ambiguous}
    )


def list_cameras(site=None) -> list[dict]:
    if not db_available():
        return []
    from core.models import Camera

    from django.db.models import Count

    qs = Camera.objects.select_related("zone", "stream_connection").filter(**_site_filter_kwargs(site)).annotate(frame_count=Count("observations"))
    cameras = []
    for cam in qs:
        latest = _latest_observation_for_zone(cam.zone.external_id, site=site)
        cameras.append(
            {
                "camera_id": cam.external_id,
                "name": cam.name,
                "zone_id": cam.zone.external_id,
                "zone_name": cam.zone.name,
                "latitude": cam.latitude,
                "longitude": cam.longitude,
                "stream_url": cam.stream_url,
                **camera_stream_state(cam),
                "is_demo": cam.is_demo,
                "observation_count": cam.frame_count,
                "latest_observation": _observation_summary(latest) if latest else None,
            }
        )
    return cameras


def get_camera(camera_id: str, site=None) -> dict | None:
    if not db_available():
        return None
    from core.models import Camera

    cam_qs = Camera.objects.select_related("zone", "stream_connection").filter(
        external_id=camera_id, **_site_filter_kwargs(site)
    )
    cam = cam_qs.first()
    if cam is None:
        return None

    from core.models import Observation

    recent = (
        Observation.objects.filter(zone=cam.zone)
        .prefetch_related("detections")
        .order_by("-created_at")[:10]
    )
    recent_list = list(recent)
    return {
        "camera_id": cam.external_id,
        "name": cam.name,
        "zone_id": cam.zone.external_id,
        "zone_name": cam.zone.name,
        "latitude": cam.latitude,
        "longitude": cam.longitude,
        "stream_url": cam.stream_url,
                **camera_stream_state(cam),
        "is_demo": cam.is_demo,
        "latest_observation": _observation_summary(recent_list[0]) if recent_list else None,
        "recent_observations": [_observation_summary(o) for o in recent_list],
    }


def timeline(zone_id: str | None, days: int = 14, site=None) -> dict:
    if not db_available():
        return {"available": False, "points": []}
    from core.models import Observation

    since = datetime.now(UTC) - timedelta(days=days)
    qs = Observation.objects.filter(created_at__gte=since, **_site_filter_kwargs(site)).select_related("zone")
    if zone_id:
        qs = qs.filter(zone__external_id=zone_id)
    points = [
        {
            "observation_id": str(o.id),
            "created_at": o.created_at.isoformat(),
            "overall_status": o.overall_status,
            "zone_id": o.zone.external_id,
        }
        for o in qs.order_by("created_at")
    ]
    return {"available": True, "points": points}


def notifications(limit: int = 20, site=None) -> dict:
    if not db_available():
        return {"available": False, "items": []}
    from core.models import Observation

    qs = Observation.objects.filter(
        overall_status__in=["possible_deviation", "insufficient_data"], **_site_filter_kwargs(site)
    )
    qs = qs.select_related("zone").prefetch_related("stage_evaluations").order_by("-created_at")[:limit]
    items = []
    for obs in qs:
        stage_eval = next(
            (e for e in obs.stage_evaluations.all() if e.status == obs.overall_status), None
        )
        items.append(
            {
                "observation_id": str(obs.id),
                "severity": "critical" if obs.overall_status == "possible_deviation" else "info",
                "zone_id": obs.zone.external_id,
                "zone_name": obs.zone.name,
                "created_at": obs.created_at.isoformat(),
                "title": stage_eval.work_name_snapshot if stage_eval else obs.zone.name,
                "explanation_ru": stage_eval.explanation if stage_eval else obs.overall_explanation,
                "status_label_ru": obs.get_overall_status_display(),
                "quantity_checks": stage_eval.quantity_checks_snapshot if stage_eval else [],
            }
        )
    return {"available": True, "items": items}


def analytics(days: int = 14, site=None) -> dict:
    """days <= 0 означает «за всё время» — без нижней границы по дате, страница Аналитики
    показывает агрегаты по всему проекту.
    """
    if not db_available():
        return {"available": False, "deviations_by_month": [], "equipment_counts": [], "total_observations": 0}
    from core.models import Detection, Observation

    since = datetime.now(UTC) - timedelta(days=days) if days and days > 0 else None
    time_filter = {"created_at__gte": since} if since is not None else {}
    observations = Observation.objects.filter(**time_filter, **_site_filter_kwargs(site))

    # Группировка по месяцу съёмки (не по дню): аналитика часто охватывает весь
    # проект целиком (месяцы или годы), и поденный бар-чарт с колонкой на каждый
    # календарный день растягивается в длинную горизонтально-скроллящуюся полосу почти
    # пустых столбиков. Дата берётся из `observed_date` (историческая дата съёмки), а не из
    # `created_at` (реальное время загрузки в систему) — с фолбэком на `created_at`, если дата
    # съёмки не подтверждена.
    deviations_by_month: dict[str, int] = {}
    for obs in observations.filter(overall_status="possible_deviation"):
        month_source = obs.observed_date if obs.date_confirmed and obs.observed_date else obs.created_at.date()
        month_key = month_source.strftime("%Y-%m")
        deviations_by_month[month_key] = deviations_by_month.get(month_key, 0) + 1

    equipment_by_class: dict[str, int] = {}
    site_kwargs = {f"observation__{k}": v for k, v in _site_filter_kwargs(site).items()}
    detection_time_filter = {"observation__created_at__gte": since} if since is not None else {}
    detections = Detection.objects.filter(
        **detection_time_filter, in_taxonomy=True, ambiguous=False, **site_kwargs
    ).values_list("class_key", "label_ru")
    labels_by_class: dict[str, str] = {}
    for class_key, label_ru in detections:
        equipment_by_class[class_key] = equipment_by_class.get(class_key, 0) + 1
        labels_by_class[class_key] = label_ru

    return {
        "available": True,
        "deviations_by_month": [{"month": m, "count": c} for m, c in sorted(deviations_by_month.items())],
        "equipment_counts": [
            {"class_key": k, "label_ru": labels_by_class[k], "count": c}
            for k, c in sorted(equipment_by_class.items(), key=lambda kv: -kv[1])
        ],
        "total_observations": observations.count(),
    }


def _stage_progress_percent(stage: Stage, today: date) -> float | None:
    """Only recorded physical measurements can be shown as completion."""
    if (stage.verified_progress_percent is not None and stage.verified_progress_date is not None
        and stage.verified_progress_date <= today and stage.verified_progress_note.strip()):
        return stage.verified_progress_percent
    return None


@dataclass(frozen=True)
class ZoneRef:
    zone_id: str
    name: str


def latest_confirmed_date(site) -> date | None:
    if site is not None and db_available():
        from core.models import Observation
        latest = Observation.objects.filter(zone__site=site, date_confirmed=True,
                    observed_date__isnull=False).order_by("-observed_date").first()
        if latest is not None:
            return latest.observed_date
    return None


def reference_date(site, today: date) -> date:
    """A paused site's operational view is anchored to its last confirmed photo."""
    if site is not None and site.status == "paused":
        return latest_confirmed_date(site) or today
    return today


def dashboard_summary(
    *,
    schedule: Schedule,
    zones: list[ZoneRef],
    today: date,
    weather_rules: list[WeatherRule] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    site=None,
) -> dict:
    paused = site is not None and site.status == "paused"
    view_date = reference_date(site, today)
    active_stages = [s for s in schedule.stages if s.is_active_on(view_date) and s.stage_id not in schedule.summary_stage_ids()]
    current_stage = None
    if active_stages:
        stage = (max if paused else min)(active_stages, key=lambda s: (s.start_date, s.stage_id))
        current_stage = {
            "stage_id": stage.stage_id,
            "work_name": stage.work_name,
            "zone_id": stage.zone_id,
            "start_date": stage.start_date.isoformat(),
            "end_date": stage.end_date.isoformat(),
            "progress_percent": None if paused else _stage_progress_percent(stage, today),
        }

    zone_summaries = []
    detected_classes: set[str] = set()
    for zone in zones:
        latest = _latest_observation_for_zone(zone.zone_id, site=site) if db_available() else None
        zone_summaries.append(
            {
                "zone_id": zone.zone_id,
                "name": zone.name,
                "latest_observation": _observation_summary(latest) if latest else None,
            }
        )
        detected_classes |= set(_detected_classes(latest))

    cameras = list_cameras(site=site)

    top_risk_factor = None
    if not paused and current_stage is not None and weather_rules is not None and latitude is not None and longitude is not None:
        stage_obj = next(s for s in schedule.stages if s.stage_id == current_stage["stage_id"])
        stage_forecast = forecast_for_stage(
            stage=stage_obj,
            schedule=schedule,
            weather_rules=weather_rules,
            latitude=latitude,
            longitude=longitude,
            today=today,
            site=site,
            include_weather=False,
        )
        if stage_forecast["risk_factors"]:
            top_risk_factor = stage_forecast["risk_factors"][0]

    deviations_24h = deviations_7d = 0
    if db_available():
        from core.models import Observation

        now = datetime.now(UTC)
        deviation_qs = Observation.objects.filter(
            overall_status="possible_deviation", **_site_filter_kwargs(site)
        )
        deviations_24h = deviation_qs.filter(created_at__gte=now - timedelta(hours=24)).count()
        deviations_7d = deviation_qs.filter(created_at__gte=now - timedelta(days=7)).count()

    return {
        "available": db_available(),
        "project_status": site.status if site is not None else "construction",
        "reference_date": view_date.isoformat(),
        "last_observed_date": latest_confirmed_date(site).isoformat() if latest_confirmed_date(site) else None,
        "zone_count": len(zones),
        "camera_count": len(cameras),
        "active_stage_count": len(active_stages),
        "current_stage": current_stage,
        "plan_completion_percent": current_stage["progress_percent"] if current_stage else None,
        "recognized_equipment_type_count": len(detected_classes),
        "deviation_count_24h": deviations_24h,
        "deviation_count_7d": deviations_7d,
        "zones": zone_summaries,
        "cameras": cameras,
        "top_risk_factor": top_risk_factor,
        "recent_deviations": notifications(limit=5, site=site)["items"],
    }

def camera_stream_state(camera):
    from core.models import CameraStreamConnection
    try:c=camera.stream_connection
    except CameraStreamConnection.DoesNotExist:return {'stream_online':False,'stream_capture_enabled':False,'last_frame_received_at':None}
    now=datetime.now(UTC)
    return {'stream_online':bool(c.enabled and c.last_success_at and now-c.last_success_at<timedelta(minutes=max(c.interval_minutes*2,5))),'stream_capture_enabled':c.enabled,'last_frame_received_at':c.last_success_at.isoformat() if c.last_success_at else None}
