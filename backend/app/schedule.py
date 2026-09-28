"""График работ и площадка.

Основной источник — таблицы core.Stage/Zone/ConstructionSite в PostgreSQL
(редактируются через Django admin). Резервный откат при недоступности
БД — data/config/demo_schedule.json и demo_site.geojson.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import django_bridge
from .config import DEMO_SCHEDULE_PATH, DEMO_SITE_GEOJSON_PATH


@dataclass(frozen=True)
class Stage:
    stage_id: str
    work_code: str
    work_name: str
    zone_id: str
    start_date: date
    end_date: date
    technology_assumption: str
    is_demo: bool
    #: Укрупнённая работа, в которую входит этап: заказчик работает с четырьмя уровнями.
    parent_id: str | None = None
    #: Связи «окончание-начало» — основа расчёта критического пути.
    predecessor_ids: tuple[str, ...] = ()

    def is_active_on(self, day: date) -> bool:
        return self.start_date <= day <= self.end_date


@dataclass(frozen=True)
class Schedule:
    is_demo: bool
    stages: list[Stage]

    def stages_for_zone(self, zone_id: str) -> list[Stage]:
        return [s for s in self.stages if s.zone_id == zone_id]

    def summary_stage_ids(self) -> set[str]:
        """Укрупнённые работы — те, у кого есть вложенные."""
        return {s.parent_id for s in self.stages if s.parent_id}

    def active_stages(self, zone_id: str, day: date) -> list[Stage]:
        """Активные листовые работы зоны на дату.

        Раздел графика («Подземная часть») проверять по составу техники
        бессмысленно: своей технологии у него нет, он только группирует работы.
        Иначе каждый снимок получал бы пустое «нет правила для этапа» в нагрузку.
        """
        summaries = self.summary_stage_ids()
        return [
            s
            for s in self.stages_for_zone(zone_id)
            if s.is_active_on(day) and s.stage_id not in summaries
        ]

    def by_id(self, stage_id: str) -> Stage | None:
        return next((s for s in self.stages if s.stage_id == stage_id), None)


def _load_schedule_from_file(path: Path = DEMO_SCHEDULE_PATH) -> Schedule:
    data = json.loads(path.read_text(encoding="utf-8"))
    is_demo = bool(data.get("is_demo", False))
    stages = [
        Stage(
            stage_id=entry["stage_id"],
            work_code=entry.get("work_code") or entry.get("parent_work_code", ""),
            work_name=entry["work_name"],
            zone_id=entry["zone_id"],
            start_date=date.fromisoformat(entry["start_date"]),
            end_date=date.fromisoformat(entry["end_date"]),
            technology_assumption=entry.get("technology_assumption", ""),
            is_demo=is_demo,
            parent_id=entry.get("parent_stage_id"),
            predecessor_ids=tuple(entry.get("predecessor_ids") or ()),
        )
        for entry in data["stages"]
    ]
    return Schedule(is_demo=is_demo, stages=stages)


def _load_schedule_from_db(site=None) -> Schedule:
    from core.models import Stage as StageRow

    qs = StageRow.objects.select_related("zone", "parent").prefetch_related("predecessors")
    qs = qs.filter(zone__site=site) if site is not None else qs.filter(zone__site__is_legacy=True)
    rows = list(qs)
    if not rows:
        if site is not None:
            # Пустой новый проект без графика — честное пустое состояние, не ошибка.
            return Schedule(is_demo=False, stages=[])
        raise ValueError("Этапы графика legacy-проекта в БД пусты — выполните `python manage.py seed_demo_data`")

    stages = [
        Stage(
            stage_id=row.external_id,
            work_code=row.work_code,
            work_name=row.work_name,
            zone_id=row.zone.external_id,
            start_date=row.start_date,
            end_date=row.end_date,
            technology_assumption=row.technology_assumption,
            is_demo=row.is_demo,
            parent_id=row.parent.external_id if row.parent else None,
            predecessor_ids=tuple(
                sorted(item.external_id for item in row.predecessors.all())
            ),
        )
        for row in rows
    ]
    return Schedule(is_demo=all(s.is_demo for s in stages), stages=stages)


def load_schedule(path: Path = DEMO_SCHEDULE_PATH, site=None) -> Schedule:
    # site=None -> legacy-проект с откатом на файл; явно заданный site -
    # строгая проверка без отката на демофайл (см. план «API изоляция»).
    if django_bridge.ensure_django_ready():
        try:
            return _load_schedule_from_db(site=site)
        except Exception:
            if site is not None:
                raise
            django_bridge.logger.exception("Не удалось загрузить график из БД, откат на файл")
    elif site is not None:
        from fastapi import HTTPException

        raise HTTPException(503, "База данных недоступна")
    return _load_schedule_from_file(path)


def _load_site_geojson_from_file(path: Path = DEMO_SITE_GEOJSON_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_site_geojson_from_db(site=None) -> dict:
    from core.models import ConstructionSite

    if site is None:
        site = ConstructionSite.objects.filter(is_legacy=True).prefetch_related("zones").first()
        if site is None:
            raise ValueError("Legacy-проект в БД не найден — выполните `python manage.py seed_demo_data`")

    features = []
    if site.boundary_geojson:
        features.append(
            {
                "type": "Feature",
                "properties": {"kind": "site_boundary", "id": f"site-{site.pk}", "name": site.name},
                "geometry": site.boundary_geojson,
            }
        )
    for zone in site.zones.all():
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "zone",
                    "id": zone.external_id,
                    "name": zone.name,
                    "description": zone.description,
                    # "zone_kind" -- справочный тип зоны площадки (Zone.kind). Назван не
                    # "kind", чтобы не перекрывать вышестоящий "kind": "zone" (тип feature на карте).
                    "zone_kind": zone.kind,
                    "zone_kind_label_ru": zone.get_kind_display(),
                },
                "geometry": zone.geometry_geojson,
            }
        )
        for camera in zone.cameras.all():
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "kind": "camera",
                        "id": camera.external_id,
                        "name": camera.name,
                        "zone_id": zone.external_id,
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [camera.longitude, camera.latitude],
                    },
                }
            )

    return {
        "type": "FeatureCollection",
        "properties": {"is_demo": site.is_demo, "note": site.note},
        "features": features,
    }


def load_site_geojson(path: Path = DEMO_SITE_GEOJSON_PATH, site=None) -> dict:
    if django_bridge.ensure_django_ready():
        try:
            return _load_site_geojson_from_db(site=site)
        except Exception:
            if site is not None:
                raise
            django_bridge.logger.exception("Не удалось загрузить площадку из БД, откат на файл")
    elif site is not None:
        from fastapi import HTTPException

        raise HTTPException(503, "База данных недоступна")
    return _load_site_geojson_from_file(path)


def site_centroid(geojson: dict) -> tuple[float, float] | None:
    """Центроид границы площадки для запроса погоды.

    Простое среднее вершин, а не точный геометрический центроид —
    для небольшого почти прямоугольного участка этого достаточно точно.
    Возвращает None, если у проекта ещё нет границы (новый проект без геометрии) —
    вызывающий код должен честно обработать отсутствие местоположения, а не подставлять московскую демоплощадку.
    """
    for feature in geojson.get("features", []):
        if feature.get("properties", {}).get("kind") == "site_boundary":
            ring = feature["geometry"]["coordinates"][0]
            lons = [pt[0] for pt in ring]
            lats = [pt[1] for pt in ring]
            return sum(lats) / len(lats), sum(lons) / len(lons)
    return None
