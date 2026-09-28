"""Проектные маршруты: список/создание проектов + scoped-зеркала /api/... .

См. план «выбор и создание проектов», разделы «Данные и разграничение
доступа» и «API изоляция». Контекст проекта резолвится явно через
`project_scope.get_project_site`/`get_project_scope` на каждый запрос —
никакого общего «выбранного проекта» на сервере не хранится.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from . import (
    assistant,
    auth,
    config,
    demo,
    frame_zones,
    insights,
    learning,
    observation_ai,
    persistence,
    readiness,
    schedule_import,
    schedule_network,
    supervision,
)
from . import deviations as deviations_module
from . import forecast as forecast_module
from .app_context import get_context
from .detector import get_detector
from .matching import evaluate_observation
from .project_scope import get_project_site
from .weather import (
    fetch_current_weather,
    fetch_daily_forecast,
    fetch_forecast,
    weather_code_label_ru,
)
from .weather_matching import evaluate_weather_risks

#: Camera/Zone/Stage external_id — SlugField без allow_unicode, поэтому
#: пользовательский идентификатор камеры проверяется этим же regex, что и
#: django.core.validators.validate_slug.
_SLUG_RE = re.compile(r"^[-a-zA-Z0-9_]+$")

router = APIRouter(prefix="/api")


def _image_size(path: Path) -> tuple[int, int]:
    """Размер снимка нужен, чтобы пересчитать зоны под другое разрешение кадра."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        return (0, 0)


# --------------------------------------------------------------------------
# Список / создание проектов
# --------------------------------------------------------------------------


def _status_choices() -> dict[str, str]:
    from core.models import ConstructionSite

    return dict(ConstructionSite.Status.choices)


def _project_summary(site, current_user: auth.CurrentUser) -> dict:
    """Карточка для списка. Дополнительные поля намеренно дешёвые (простые счётчики/первый
    .first()) — никакого расчёта сетевого графика или прогноза на карточку, чтобы список проектов
    оставался лёгким даже при большом числе проектов."""
    from core.models import Camera, Deviation, Observation, Stage

    today = datetime.now(UTC).date()
    current_stage = (
        Stage.objects.filter(zone__site=site, start_date__lte=today, end_date__gte=today)
        .order_by("start_date")
        .first()
    )
    current_stage_progress_percent = None
    if current_stage is not None:
        total_days = (current_stage.end_date - current_stage.start_date).days + 1
        if total_days > 0:
            elapsed_days = (min(today, current_stage.end_date) - current_stage.start_date).days + 1
            current_stage_progress_percent = round(
                max(0.0, min(1.0, elapsed_days / total_days)) * 100, 1
            )

    # Первая камера с хотя бы одним наблюдением — только для превью на карточке, без лишних
    # запросов к детекциям/эвалюациям.
    photo_camera = (
        Camera.objects.filter(zone__site=site, observations__isnull=False)
        .order_by("external_id")
        .distinct()
        .first()
    )

    return {
        "project_id": site.pk,
        "name": site.name,
        "address": site.address,
        "status": site.status,
        "status_label_ru": dict(_status_choices()).get(site.status, site.status),
        "latitude": site.latitude,
        "longitude": site.longitude,
        "has_boundary": bool(site.boundary_geojson),
        "is_legacy": site.is_legacy,
        "current_stage_work_name": current_stage.work_name if current_stage else None,
        "current_stage_progress_percent": current_stage_progress_percent,
        "photo_camera_id": photo_camera.external_id if photo_camera else None,
        "total_observations": Observation.objects.filter(zone__site=site).count(),
        "open_deviations_count": Deviation.objects.filter(
            zone__site=site, status__in=Deviation.OPEN_STATUSES
        ).count(),
    }


@router.get("/projects")
def list_projects(current_user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    """Проекты, доступные пользователю: администратор видит все, участник — только назначенные."""
    from core.models import ConstructionSite

    if current_user.role == "admin":
        sites = ConstructionSite.objects.all().order_by("name")
    else:
        sites = ConstructionSite.objects.filter(memberships__user_id=current_user.id).order_by("name")
    return {"projects": [_project_summary(site, current_user) for site in sites]}


@router.get("/supervision")
def get_supervision_portfolio(
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> dict:
    """Участок надзора: все доступные объекты с их состоянием на одном экране."""
    return supervision.portfolio(
        user_id=current_user.id, is_admin=current_user.role == "admin"
    )


@router.get("/supervision/queue")
def get_supervision_queue(
    limit: int = 40,
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> dict:
    """Очередь разбора поверх всех объектов инспектора."""
    return supervision.review_queue(
        user_id=current_user.id,
        is_admin=current_user.role == "admin",
        limit=min(limit, 200),
    )


@router.get("/projects/statuses")
def get_project_statuses(current_user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    return {"statuses": [{"key": k, "label_ru": v} for k, v in _status_choices().items()]}


@router.get("/projects/assignable-users")
def list_assignable_users(current_user: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    """Пользователи, которых администратор может назначить на проект. Без секретных полей."""
    from django.contrib.auth.models import User

    users = User.objects.filter(is_active=True).order_by("username")
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.get_full_name() or u.username,
            }
            for u in users
        ]
    }


class ProjectCreateRequest(BaseModel):
    """Сохранено только для документации формы — сам эндпоинт принимает multipart (см. create_project)."""

    name: str = Field(min_length=1, max_length=200)
    address: str = Field(default="", max_length=300)
    status: str = "construction"
    latitude: float | None = None
    longitude: float | None = None
    member_user_ids: list[int] = Field(default_factory=list)


def _parse_boundary_geojson(raw: str | None) -> dict | None:
    """`[[lon, lat], ...]` из формы → GeoJSON Polygon. `None`, если граница не задана."""
    if raw is None or raw.strip() == "":
        return None
    try:
        points = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "boundary_geojson должен быть валидным JSON") from exc
    if not isinstance(points, list) or len(points) < 3:
        raise HTTPException(400, "Граница площадки должна содержать не менее трёх точек")

    ring: list[list[float]] = []
    for point in points:
        if not (isinstance(point, list) and len(point) == 2):
            raise HTTPException(400, "Каждая точка границы должна быть парой [долгота, широта]")
        try:
            lon, lat = float(point[0]), float(point[1])
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Координаты границы должны быть числами") from exc
        if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            raise HTTPException(400, "Координаты границы вне допустимого диапазона")
        ring.append([lon, lat])
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return {"type": "Polygon", "coordinates": [ring]}


def _validate_camera_external_id(value: str) -> None:
    if not _SLUG_RE.fullmatch(value):
        raise HTTPException(
            400,
            "Идентификатор камеры может содержать только латинские буквы, цифры, дефис и подчёркивание",
        )


class CameraPayload(BaseModel):
    """Одна камера из списка на шаге «Камеры и трансляции» визарда создания проекта.

    Отдельно от одиночной камеры, привязанной к загружаемым фото (см. camera_name/
    camera_external_id выше) — эти камеры создаются без привязки к фото, только для ссылок
    на трансляцию и отображения на карте.
    """

    name: str = Field(min_length=1, max_length=200)
    external_id: str | None = None
    stream_url: str = Field(default="", max_length=500)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


@router.get("/projects/schedule-template")
def download_schedule_template(
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> Response:
    """Шаблон `.xlsx` календарного плана для формы создания проекта (см. schedule_import.py)."""
    buffer = schedule_import.build_template_workbook()
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="schedule_template.xlsx"'},
    )


@router.post("/projects")
def create_project(
    name: str = Form(...),
    address: str = Form(""),
    status: str = Form("construction"),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    member_user_ids: list[int] = Form(default_factory=list),
    stream_url: str = Form(""),
    boundary_geojson: str | None = Form(None),
    schedule_excel: UploadFile | None = File(None),
    photos: list[UploadFile] = File(default_factory=list),
    camera_name: str | None = Form(None),
    camera_external_id: str | None = Form(None),
    camera_latitude: float | None = Form(None),
    camera_longitude: float | None = Form(None),
    camera_zone_name: str | None = Form(None),
    frame_zones: str | None = Form(None),
    reference_width: int | None = Form(None),
    reference_height: int | None = Form(None),
    cameras: str | None = Form(None),
    current_user: auth.CurrentUser = Depends(auth.require_admin),
) -> dict:
    """Создаёт проект вместе с границей, графиком, фото и зонами кадра одной формой.

    Один multipart-запрос, без промежуточных «черновиков» на сервере (см. план
    «Расширение страницы «Новый проект»»). Валидация — целиком до открытия
    транзакции: при любой ошибке проект не создаётся вообще. Обработка фото —
    тяжёлая CPU-операция, поэтому идёт уже после коммита; ошибка на одном фото
    не должна прервать анализ остальных.
    """
    from django.contrib.auth.models import User
    from django.db import transaction

    from core.models import Camera, ConstructionSite, ProjectMembership, Stage, Zone

    trimmed_name = name.strip()
    if not trimmed_name:
        raise HTTPException(400, "Название проекта не может быть пустым")

    valid_statuses = set(_status_choices())
    if status not in valid_statuses:
        raise HTTPException(400, f"Недопустимый статус проекта: {status}")

    if (latitude is None) != (longitude is None):
        raise HTTPException(400, "Широта и долгота должны быть заданы вместе или отсутствовать вместе")
    if latitude is not None and not (-90 <= latitude <= 90):
        raise HTTPException(400, "Широта должна быть в диапазоне [-90, 90]")
    if longitude is not None and not (-180 <= longitude <= 180):
        raise HTTPException(400, "Долгота должна быть в диапазоне [-180, 180]")

    member_ids = set(member_user_ids)
    if member_ids:
        found_ids = set(User.objects.filter(id__in=member_ids, is_active=True).values_list("id", flat=True))
        missing = member_ids - found_ids
        if missing:
            raise HTTPException(400, f"Пользователи не найдены или неактивны: {sorted(missing)}")

    boundary_polygon = _parse_boundary_geojson(boundary_geojson)

    if len(photos) > 10:
        raise HTTPException(400, "Не более 10 фотографий за один раз — остальные можно добавить позже")
    for photo in photos:
        if photo.content_type and not photo.content_type.startswith("image/"):
            raise HTTPException(400, f"Файл «{photo.filename}» не является изображением")

    parsed_schedule: schedule_import.ParsedSchedule | None = None
    if schedule_excel is not None:
        parse_result = schedule_import.parse_schedule_workbook(schedule_excel.file)
        if isinstance(parse_result, list):
            raise HTTPException(400, {"message": "Ошибки в календарном плане", "errors": parse_result})
        parsed_schedule = parse_result

    camera_payloads: list[CameraPayload] = []
    if cameras:
        try:
            raw_cameras = json.loads(cameras)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "cameras должен быть валидным JSON") from exc
        try:
            camera_payloads = TypeAdapter(list[CameraPayload]).validate_python(raw_cameras)
        except ValidationError as exc:
            raise HTTPException(400, f"Некорректный формат списка камер: {exc.errors()}") from exc
        for cam in camera_payloads:
            if not cam.name.strip():
                raise HTTPException(400, "Название камеры не может быть пустым")
        for cam in camera_payloads:
            if cam.external_id:
                _validate_camera_external_id(cam.external_id)

    if (parsed_schedule is not None or photos or camera_payloads) and boundary_polygon is None:
        raise HTTPException(
            400,
            "Сначала отметьте границу площадки на карте — она нужна как геометрия зон для "
            "календарного плана, фотографий и камер", 
        )

    frame_zone_payloads: list[FrameZonePayload] = []
    if frame_zones:
        if not photos:
            raise HTTPException(
                400, "Зоны кадра можно задать только вместе с загруженными фотографиями и камерой"
            )
        try:
            raw_zones = json.loads(frame_zones)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "frame_zones должен быть валидным JSON") from exc
        try:
            frame_zone_payloads = TypeAdapter(list[FrameZonePayload]).validate_python(raw_zones)
        except ValidationError as exc:
            raise HTTPException(400, f"Некорректный формат зон кадра: {exc.errors()}") from exc
        _validate_frame_zone_payloads(frame_zone_payloads)
        if not reference_width or not reference_height:
            raise HTTPException(
                400, "Для зон кадра нужны размеры опорного фото (reference_width/height)"
            )

    camera_requested = bool(photos)
    effective_camera_latitude: float | None = None
    effective_camera_longitude: float | None = None
    if camera_requested:
        if not camera_name or not camera_name.strip():
            raise HTTPException(400, "Укажите название камеры для загруженных фотографий")
        effective_camera_latitude = camera_latitude if camera_latitude is not None else latitude
        effective_camera_longitude = camera_longitude if camera_longitude is not None else longitude
        if effective_camera_latitude is None or effective_camera_longitude is None:
            raise HTTPException(
                400,
                "Не заданы координаты камеры — укажите точку камеры или точку проекта на карте",
            )
        if camera_external_id:
            _validate_camera_external_id(camera_external_id)
            if Camera.objects.filter(external_id=camera_external_id).exists():
                raise HTTPException(400, f"Идентификатор камеры уже используется: {camera_external_id}")

    requested_external_ids: list[str] = [c.external_id for c in camera_payloads if c.external_id]
    if camera_requested and camera_external_id:
        requested_external_ids.append(camera_external_id)
    if len(requested_external_ids) != len(set(requested_external_ids)):
        raise HTTPException(400, "Идентификаторы камер должны быть уникальными")
    if requested_external_ids:
        existing_ids = set(
            Camera.objects.filter(external_id__in=requested_external_ids).values_list(
                "external_id", flat=True
            )
        )
        if existing_ids:
            raise HTTPException(400, f"Идентификаторы камер уже используются: {sorted(existing_ids)}")

    with transaction.atomic():
        site = ConstructionSite.objects.create(
            name=trimmed_name,
            address=address.strip(),
            status=status,
            latitude=latitude,
            longitude=longitude,
            is_demo=False,
            boundary_geojson=boundary_polygon,
            stream_url=stream_url.strip(),
            created_by_id=current_user.id,
        )
        ProjectMembership.objects.bulk_create(
            [ProjectMembership(site=site, user_id=uid) for uid in member_ids]
        )
        # Администратор создаёт проект и должен сразу его видеть в своём списке,
        # даже если сам себя явно не указал среди участников (роль админ и так
        # даёт доступ ко всем проектам — членство здесь не обязательно).

        zones_by_name: dict[str, Zone] = {}
        stages_created = 0
        if parsed_schedule is not None:
            # Все зоны из Excel получают одну и ту же геометрию — границу площадки,
            # нарисованную на карте; уточнить геометрию можно позже через Django admin.
            for index, zone_name in enumerate(parsed_schedule.zone_names, start=1):
                zones_by_name[zone_name] = Zone.objects.create(
                    site=site,
                    external_id=f"site{site.pk}-zone-{index}",
                    name=zone_name,
                    geometry_geojson=boundary_polygon,
                )
            stages_by_row: dict[int, Stage] = {}
            for row in parsed_schedule.rows:
                stages_by_row[row.row_number] = Stage.objects.create(
                    external_id=f"site{site.pk}-stage-{row.row_number}",
                    zone=zones_by_name[row.zone_name],
                    work_code=row.work_code,
                    work_name=row.work_name,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    technology_assumption=row.technology_assumption,
                    is_demo=False,
                )
            # Второй проход нужен, чтобы ссылки на родителя/предшественников могли указывать
            # на ещё не созданные на момент первого прохода строки.
            for row in parsed_schedule.rows:
                stage = stages_by_row[row.row_number]
                if row.parent_row_number is not None:
                    stage.parent = stages_by_row[row.parent_row_number]
                    stage.save(update_fields=["parent"])
                if row.predecessor_row_numbers:
                    stage.predecessors.set([stages_by_row[p] for p in row.predecessor_row_numbers])
            stages_created = len(parsed_schedule.rows)
        elif boundary_polygon is not None:
            # Без календарного плана, но с границей — единая зона «Площадка», чтобы
            # было куда привязать фотографии и камеру (см. план).
            zones_by_name["Площадка"] = Zone.objects.create(
                site=site,
                external_id=f"site{site.pk}-zone-1",
                name="Площадка",
                geometry_geojson=boundary_polygon,
            )

        camera = None
        if camera_requested:
            target_zone = zones_by_name.get(camera_zone_name) if camera_zone_name else None
            if target_zone is None:
                target_zone = next(iter(zones_by_name.values()))
            camera = Camera.objects.create(
                zone=target_zone,
                external_id=camera_external_id or f"site{site.pk}-cam-1",
                name=camera_name.strip(),
                latitude=effective_camera_latitude,
                longitude=effective_camera_longitude,
                is_demo=False,
            )

        cameras_created = 0
        if camera_payloads:
            # Все дополнительные камеры идут в одну и ту же зону — точная привязка к
            # зоне не важна для камер без фото: они существуют только ради ссылки на
            # трансляцию и точки на карте, а не для анализа снимков.
            extra_target_zone = next(iter(zones_by_name.values()))
            for index, cam in enumerate(camera_payloads, start=1):
                Camera.objects.create(
                    zone=extra_target_zone,
                    external_id=cam.external_id or f"site{site.pk}-cam-extra-{index}",
                    name=cam.name.strip(),
                    latitude=cam.latitude,
                    longitude=cam.longitude,
                    stream_url=cam.stream_url.strip(),
                    is_demo=False,
                )
            cameras_created = len(camera_payloads)

    # Обработка фото — тяжёлая CPU-операция, поэтому вне транзакции: ошибка детектора
    # на одном фото не должна откатывать уже созданный проект.
    photo_results: list[dict] = []
    for photo in photos:
        try:
            pipeline_result = _run_observation_pipeline(
                site=site,
                zone_id=camera.zone.external_id,
                observed_date=None,
                date_confirmed=False,
                camera_id=camera.external_id if camera else None,
                image=photo,
                require_zone_in_schedule=False,
            )
            photo_results.append(
                {
                    "filename": photo.filename,
                    "status": "ok",
                    "observation_id": pipeline_result["observation_id"],
                    "detections_count": len(pipeline_result["detections"]),
                }
            )
        except Exception as exc:  # одно фото не должно прерывать остальные
            photo_results.append(
                {
                    "filename": photo.filename,
                    "status": "error",
                    "error": exc.detail if isinstance(exc, HTTPException) else str(exc),
                }
            )

    frame_zones_saved = False
    if frame_zone_payloads and camera is not None:
        _replace_frame_zones(camera, frame_zone_payloads, reference_width, reference_height)
        frame_zones_saved = True

    return {
        "project": _project_summary(site, current_user),
        "schedule_import": {"zones_created": len(zones_by_name), "stages_created": stages_created},
        "photos": photo_results,
        "frame_zones_saved": frame_zones_saved,
        "cameras_created": cameras_created,
    }


@router.get("/projects/{project_id}")
def get_project_detail(site=Depends(get_project_site)) -> dict:
    return {
        "project_id": site.pk,
        "name": site.name,
        "address": site.address,
        "status": site.status,
        "status_label_ru": dict(_status_choices()).get(site.status, site.status),
        "latitude": site.latitude,
        "longitude": site.longitude,
        "has_boundary": bool(site.boundary_geojson),
        "is_legacy": site.is_legacy,
        "note": site.note,
    }


@router.get("/projects/{project_id}/members")
def list_project_members(
    project_id: int,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    from core.models import ProjectMembership

    memberships = ProjectMembership.objects.filter(site=site).select_related("user").order_by("user__username")
    return {
        "members": [
            {"id": m.user_id, "username": m.user.username, "full_name": m.user.get_full_name() or m.user.username}
            for m in memberships
        ]
    }


class ProjectDeleteRequest(BaseModel):
    """Требует повторный ввод названия проекта — защита от случайного удаления
    необратимого действия (снимки, отклонения, история — всё стирается безвозвратно).
    """

    confirm_name: str = Field(min_length=1, max_length=200)


@router.delete("/projects/{project_id}")
def delete_project(
    payload: ProjectDeleteRequest,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Удаляет проект целиком: зоны, этапы, камеры, снимки, отклонения, события.

    Только администратор. Legacy-проект защищён от удаления — на него завязаны
    старые маршруты `/api/...` для уже установленного APK (см. project_scope.py).
    """
    from django.db import transaction

    from core.models import Observation

    if site.is_legacy:
        raise HTTPException(
            400, "Базовый (legacy) проект нельзя удалить — он используется старыми версиями приложения"
        )
    if payload.confirm_name.strip() != site.name:
        raise HTTPException(400, "Введённое название не совпадает с названием проекта")

    with transaction.atomic():
        # Observation.zone -- on_delete=PROTECT (кадры анализа защищены от случайного
        # удаления зоны), поэтому каскад из ConstructionSite сначала упёрся бы в эту
        # защиту. При удалении всего проекта это уже не «случайное» удаление зоны.
        Observation.objects.filter(zone__site_id=site.pk).delete()
        site.delete()

    return {"status": "ok"}


# --------------------------------------------------------------------------
# Scoped-зеркала существующих /api/... маршрутов (см. main.py для legacy-версий)
# --------------------------------------------------------------------------


def _detection_to_dict(detection) -> dict:
    return {
        "class_key": detection.class_key,
        "label_ru": detection.label_ru,
        "in_taxonomy": detection.in_taxonomy,
        "confidence": detection.confidence,
        "bbox": detection.bbox,
        "ambiguous": detection.ambiguous,
        "runner_up_class_key": detection.runner_up_class_key,
        # Пустая строка превращается в null: клиент должен отличать «зона не определена»
        # от зоны с пустым названием и не рисовать подпись без содержания.
        "frame_zone_name": detection.frame_zone_name or None,
        "frame_zone_kind": detection.frame_zone_kind or None,
        "activity": detection.activity,
        "activity_reason": detection.activity_reason or None,
    }


def _quantity_check_to_dict(check) -> dict:
    return {
        "class_key": check.class_key,
        "label_ru": check.label_ru,
        "required_qty": check.required_qty,
        "actual_qty": check.actual_qty,
        "satisfied": check.satisfied,
    }


@router.get("/projects/{project_id}/site")
def get_project_site_geometry(site=Depends(get_project_site)) -> dict:
    ctx = get_context(site=site)
    return {
        "geojson": ctx.site_geojson,
        "schedule_is_demo": ctx.schedule.is_demo,
        "stages": [
            {
                "stage_id": s.stage_id,
                "work_code": s.work_code,
                "work_name": s.work_name,
                "zone_id": s.zone_id,
                "start_date": s.start_date.isoformat(),
                "end_date": s.end_date.isoformat(),
                "technology_assumption": s.technology_assumption,
            }
            for s in ctx.schedule.stages
        ],
    }


@router.get("/projects/{project_id}/dashboard")
def get_project_dashboard(site=Depends(get_project_site)) -> dict:
    ctx = get_context(site=site)
    zones = [
        insights.ZoneRef(zone_id=f["properties"]["id"], name=f["properties"]["name"])
        for f in ctx.site_geojson["features"]
        if f["properties"]["kind"] == "zone"
    ]
    return insights.dashboard_summary(
        schedule=ctx.schedule,
        zones=zones,
        today=datetime.now(UTC).date(),
        weather_rules=ctx.weather_rules,
        latitude=ctx.site_latitude,
        longitude=ctx.site_longitude,
        site=site,
    )


@router.get("/projects/{project_id}/cameras")
def get_project_cameras(site=Depends(get_project_site)) -> dict:
    return {"cameras": insights.list_cameras(site=site)}


@router.get("/projects/{project_id}/cameras/{camera_id}")
def get_project_camera_detail(camera_id: str, site=Depends(get_project_site)) -> dict:
    camera = insights.get_camera(camera_id, site=site)
    if camera is None:
        raise HTTPException(404, "Камера не найдена или БД недоступна")
    return camera


# --------------------------------------------------------------------------
# Зоны и камеры площадки (редактор карты) -- отдельно от site-эндпоинта выше:
# тот отдаёт географию всей площадки одним блоком для просмотра, а эти -- дают
# редактору карты точечную CRUD-ручку, удобную для форм создания/редактирования.
# --------------------------------------------------------------------------


def _zone_kind_choices() -> list[dict]:
    from core.models import Zone

    return [{"key": key, "label_ru": label} for key, label in Zone.Kind.choices]


def _polygon_points_to_geojson(points: list[list[float]], label: str) -> dict:
    """``[[lon, lat], ...]`` из редактора карты -> GeoJSON Polygon.

    Отдельная функция от `_parse_boundary_geojson` выше: та разбирает сырую JSON-строку
    из формы create_project, а здесь payload уже разобран Pydantic.
    """
    if len(points) < 3:
        raise HTTPException(400, f"{label} должна содержать не менее трёх точек")
    ring: list[list[float]] = []
    for point in points:
        if not (isinstance(point, list) and len(point) == 2):
            raise HTTPException(400, f"{label}: каждая точка должна быть парой [долгота, широта]")
        try:
            lon, lat = float(point[0]), float(point[1])
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"{label}: координаты должны быть числами") from exc
        if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            raise HTTPException(400, f"{label}: координаты вне допустимого диапазона")
        ring.append([lon, lat])
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return {"type": "Polygon", "coordinates": [ring]}


def _zone_to_dict(zone) -> dict:
    return {
        "zone_id": zone.external_id,
        "name": zone.name,
        "kind": zone.kind,
        "kind_label_ru": zone.get_kind_display(),
        "description": zone.description,
        "geometry_geojson": zone.geometry_geojson,
        "stage_count": zone.stages.count(),
        "camera_count": zone.cameras.count(),
    }


@router.get("/projects/{project_id}/zones")
def list_project_zones(site=Depends(get_project_site)) -> dict:
    """Список зон для редактора карты — доступен любому участнику проекта (просмотр)."""
    from core.models import Zone

    zones = Zone.objects.filter(site=site).order_by("name")
    return {"zones": [_zone_to_dict(z) for z in zones], "kinds": _zone_kind_choices()}


class ZoneCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str
    points: list[list[float]] = Field(min_length=3)
    description: str = Field(default="", max_length=2000)


@router.post("/projects/{project_id}/zones")
def create_project_zone(
    payload: ZoneCreateRequest,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Создаёт новую зону на карте (только администратор): полигон, нарисованный в редакторе."""
    from core.models import Zone

    valid_kinds = {key for key, _ in Zone.Kind.choices}
    if payload.kind not in valid_kinds:
        raise HTTPException(400, f"Недопустимый тип зоны: {payload.kind}")
    trimmed_name = payload.name.strip()
    if not trimmed_name:
        raise HTTPException(400, "Название зоны не может быть пустым")
    geometry = _polygon_points_to_geojson(payload.points, "Граница зоны")

    index = Zone.objects.filter(site=site).count() + 1
    external_id = f"site{site.pk}-zone-{index}"
    while Zone.objects.filter(external_id=external_id).exists():
        index += 1
        external_id = f"site{site.pk}-zone-{index}"

    zone = Zone.objects.create(
        site=site,
        external_id=external_id,
        name=trimmed_name,
        kind=payload.kind,
        description=payload.description.strip(),
        geometry_geojson=geometry,
    )
    return {"zone": _zone_to_dict(zone)}


class ZoneUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str
    points: list[list[float]] | None = None
    description: str = Field(default="", max_length=2000)


@router.put("/projects/{project_id}/zones/{zone_id}")
def update_project_zone(
    zone_id: str,
    payload: ZoneUpdateRequest,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Обновляет название/тип/описание зоны и, если переданы `points`, её контур.

    `points=None` оставляет геометрию как есть — редактор карты присылает их только
    при явном перерисовывании контура, а не при простой правке названия/типа.
    """
    from core.models import Zone

    zone = Zone.objects.filter(external_id=zone_id, site=site).first()
    if zone is None:
        raise HTTPException(404, "Зона не найдена в этом проекте")

    valid_kinds = {key for key, _ in Zone.Kind.choices}
    if payload.kind not in valid_kinds:
        raise HTTPException(400, f"Недопустимый тип зоны: {payload.kind}")
    trimmed_name = payload.name.strip()
    if not trimmed_name:
        raise HTTPException(400, "Название зоны не может быть пустым")

    zone.name = trimmed_name
    zone.kind = payload.kind
    zone.description = payload.description.strip()
    update_fields = ["name", "kind", "description"]
    if payload.points is not None:
        zone.geometry_geojson = _polygon_points_to_geojson(payload.points, "Граница зоны")
        update_fields.append("geometry_geojson")
    zone.save(update_fields=update_fields)
    return {"zone": _zone_to_dict(zone)}


@router.delete("/projects/{project_id}/zones/{zone_id}")
def delete_project_zone(
    zone_id: str,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Удаляет зону, только если к ней ничего не привязано.

    Без этой проверки удаление зоны с этапами графика каскадно стёрло бы их вместе с ней
    (Stage.zone -- CASCADE), а снимки вообще заблокировали бы удаление (Observation.zone -- PROTECT).
    """
    from core.models import Zone

    zone = Zone.objects.filter(external_id=zone_id, site=site).first()
    if zone is None:
        raise HTTPException(404, "Зона не найдена в этом проекте")

    stage_count = zone.stages.count()
    camera_count = zone.cameras.count()
    observation_count = zone.observations.count()
    if stage_count or camera_count or observation_count:
        parts = []
        if stage_count:
            parts.append(f"этапов графика: {stage_count}")
        if camera_count:
            parts.append(f"камер: {camera_count}")
        if observation_count:
            parts.append(f"снимков: {observation_count}")
        raise HTTPException(
            400,
            "Нельзя удалить зону — к ней всё ещё привязаны данные ("
            + ", ".join(parts)
            + "). Сначала удалите или перенесите их.",
        )
    zone.delete()
    return {"status": "ok"}


def _editable_camera_to_dict(cam) -> dict:
    return {
        "camera_id": cam.external_id,
        "name": cam.name,
        "zone_id": cam.zone.external_id,
        "zone_name": cam.zone.name,
        "latitude": cam.latitude,
        "longitude": cam.longitude,
        "stream_url": cam.stream_url,
    }


class EditableCameraCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    external_id: str | None = None
    zone_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    stream_url: str = Field(default="", max_length=500)


@router.post("/projects/{project_id}/cameras")
def create_project_camera(
    payload: EditableCameraCreateRequest,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Добавляет камеру из редактора карты (только администратор)."""
    from core.models import Camera, Zone

    zone = Zone.objects.filter(external_id=payload.zone_id, site=site).first()
    if zone is None:
        raise HTTPException(404, "Зона не найдена в этом проекте")
    trimmed_name = payload.name.strip()
    if not trimmed_name:
        raise HTTPException(400, "Название камеры не может быть пустым")

    external_id = payload.external_id
    if external_id:
        _validate_camera_external_id(external_id)
        if Camera.objects.filter(external_id=external_id).exists():
            raise HTTPException(400, f"Идентификатор камеры уже используется: {external_id}")
    else:
        index = Camera.objects.filter(zone__site=site).count() + 1
        external_id = f"site{site.pk}-cam-{index}"
        while Camera.objects.filter(external_id=external_id).exists():
            index += 1
            external_id = f"site{site.pk}-cam-{index}"

    camera = Camera.objects.create(
        zone=zone,
        external_id=external_id,
        name=trimmed_name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        stream_url=payload.stream_url.strip(),
        is_demo=False,
    )
    return {"camera": _editable_camera_to_dict(camera)}


class EditableCameraUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    zone_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    stream_url: str = Field(default="", max_length=500)


@router.put("/projects/{project_id}/cameras/{camera_id}")
def update_project_camera(
    camera_id: str,
    payload: EditableCameraUpdateRequest,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Обновляет название/позицию/ссылку/зону камеры, включая перетаскивание маркера на карте."""
    from core.models import Camera, Zone

    camera = Camera.objects.filter(external_id=camera_id, zone__site=site).first()
    if camera is None:
        raise HTTPException(404, "Камера не найдена в этом проекте")
    zone = Zone.objects.filter(external_id=payload.zone_id, site=site).first()
    if zone is None:
        raise HTTPException(404, "Зона не найдена в этом проекте")
    trimmed_name = payload.name.strip()
    if not trimmed_name:
        raise HTTPException(400, "Название камеры не может быть пустым")

    camera.name = trimmed_name
    camera.zone = zone
    camera.latitude = payload.latitude
    camera.longitude = payload.longitude
    camera.stream_url = payload.stream_url.strip()
    camera.save(update_fields=["name", "zone", "latitude", "longitude", "stream_url"])
    return {"camera": _editable_camera_to_dict(camera)}


@router.delete("/projects/{project_id}/cameras/{camera_id}")
def delete_project_camera(
    camera_id: str,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Удаляет камеру. Безопасно для истории: снимки остаются (Observation.camera -- SET_NULL),
    а зоны кадра этой камеры удаляются вместе с ней (FrameZone.camera -- CASCADE).
    """
    from core.models import Camera

    camera = Camera.objects.filter(external_id=camera_id, zone__site=site).first()
    if camera is None:
        raise HTTPException(404, "Камера не найдена в этом проекте")
    camera.delete()
    return {"status": "ok"}


@router.get("/projects/{project_id}/timeline")
def get_project_timeline(zone_id: str | None = None, days: int = 14, site=Depends(get_project_site)) -> dict:
    return insights.timeline(zone_id, days=days, site=site)


@router.get("/projects/{project_id}/analytics")
def get_project_analytics(days: int = 14, site=Depends(get_project_site)) -> dict:
    return insights.analytics(days=days, site=site)


@router.get("/projects/{project_id}/notifications")
def get_project_notifications(limit: int = 20, site=Depends(get_project_site)) -> dict:
    return insights.notifications(limit=limit, site=site)


@router.get("/projects/{project_id}/forecast")
def get_project_forecast(zone_id: str | None = None, site=Depends(get_project_site)) -> dict:
    ctx = get_context(site=site)
    today = datetime.now(UTC).date()
    stages = ctx.schedule.stages
    if zone_id:
        stages = [s for s in stages if s.zone_id == zone_id]
    active = [s for s in stages if s.is_active_on(today)]
    if not active:
        return {"available": False, "reason": "Нет активного этапа для прогноза на сегодня"}
    if ctx.site_latitude is None or ctx.site_longitude is None:
        return {"available": False, "reason": "У проекта не задано местоположение — прогноз недоступен"}

    stage = min(active, key=lambda s: s.start_date)
    result = forecast_module.forecast_for_stage(
        stage=stage,
        schedule=ctx.schedule,
        weather_rules=ctx.weather_rules,
        latitude=ctx.site_latitude,
        longitude=ctx.site_longitude,
        today=today,
        site=site,
    )
    result["available"] = True
    return result


@router.get("/projects/{project_id}/deviations")
def get_project_deviations(
    status: str | None = None,
    limit: int = 100,
    site=Depends(get_project_site),
) -> dict:
    """Отклонения проекта с их состоянием, а не лента повторяющихся сообщений."""
    return deviations_module.list_deviations(site=site, status=status, limit=min(limit, 300))


class DeviationStatusRequest(BaseModel):
    status: str
    assignee_id: int | None = None
    note: str = Field(default="", max_length=2000)


@router.post("/projects/{project_id}/deviations/{deviation_id}/status")
def change_project_deviation_status(
    deviation_id: int,
    payload: DeviationStatusRequest,
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
    site=Depends(get_project_site),
) -> dict:
    """Переводит отклонение по жизненному циклу. Доступно любому участнику проекта:
    устраняет нарушения именно инженер на площадке, а не администратор системы."""
    from core.models import Deviation

    valid = {key for key, _ in Deviation.Status.choices}
    if payload.status not in valid:
        raise HTTPException(400, f"Недопустимое состояние: {payload.status}")

    assignee_id = payload.assignee_id
    if payload.status == Deviation.Status.ASSIGNED and assignee_id is None:
        # «Назначено» без указанного ответственного — это «взять в работу на себя».
        # Отклонение без имени было бы ничейным, а ошибка на пустом месте — лишней.
        assignee_id = current_user.id

    result = deviations_module.change_status(
        deviation_id=deviation_id,
        site=site,
        status=payload.status,
        user_id=current_user.id,
        assignee_id=assignee_id,
        note=payload.note.strip(),
    )
    if result is None:
        raise HTTPException(404, "Отклонение не найдено в этом проекте или БД недоступна")
    return {"deviation": result}


@router.get("/projects/{project_id}/events")
def get_project_events(limit: int = 50, site=Depends(get_project_site)) -> dict:
    """Лента событий проекта: когда и почему состояние стало таким."""
    return deviations_module.list_events(site=site, limit=min(limit, 200))


class AssistantMessagePayload(BaseModel):
    role: str
    content: str = Field(max_length=2000)


class AssistantAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[AssistantMessagePayload] = Field(default_factory=list, max_length=8)


@router.post("/projects/{project_id}/assistant/ask")
def ask_project_assistant(
    payload: AssistantAskRequest,
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
    site=Depends(get_project_site),
) -> dict:
    """ИИ-ассистент проекта: отвечает только на основе свежего среза фактов по
    этому проекту (см. assistant.py) — не общеобразовательный чат-бот.
    Лёгкая защита от злоупотребления — то же скользящее окно, что и у публичного
    демо-разбора снимка, но ключ по пользователю, а не по IP: обращение к языковой
    модели стоит денег, и открытый чат без счётчика — приглашение положить демонстрацию.
    """
    try:
        demo.check_rate_limit(f"assistant:{current_user.id}")
    except demo.RateLimited as exc:
        raise HTTPException(
            429,
            "Слишком много вопросов ассистенту подряд. Попробуйте через "
            f"{exc.retry_after_seconds // 60 + 1} мин.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    result = assistant.answer_question(
        site=site,
        question=payload.question,
        history=[item.model_dump() for item in payload.history],
    )
    return {"available": result.available, "answer": result.answer, "error": result.error}


@router.get("/projects/{project_id}/readiness")
def get_project_readiness(site=Depends(get_project_site)) -> dict:
    """Готовность объекта во времени по фотографиям и плановые периоды работ."""
    return readiness.curve(site)


_DELAY_CATEGORY_LABELS = {
    "missing_equipment": "Недостаток техники",
    "weather": "Погода",
    "schedule_deviation": "Отставание по графику",
}


def _latest_quantity_shortfalls_for_zone(stage_id: str, zone_id: str, site) -> list[dict]:
    """Та же идея, что и `forecast.py::_latest_quantity_shortfalls`, но для любого этапа проекта,
    а не только текущего -- нужна для категоризации причин задержки по всему проекту."""
    from core.models import Observation, StageEvaluationRecord

    latest = (
        Observation.objects.filter(zone__external_id=zone_id, zone__site=site).order_by("-created_at").first()
    )
    if latest is None:
        return []
    stage_eval = StageEvaluationRecord.objects.filter(observation=latest, stage__external_id=stage_id).first()
    if not stage_eval:
        return []
    return [c for c in stage_eval.quantity_checks_snapshot if not c.get("satisfied", True)]


def _compute_delay_breakdown(report: "schedule_network.NetworkReport", ctx, site) -> dict:
    """Агрегация причин сдвига срока сдачи по категориям -- для круговой диаграммы на
    странице Календарного плана. Честность важнее точности (тот же принцип, что и в
    schedule_network.py): каждой этапу, который реально сдвигает срок сдачи (`shifts_project_finish`),
    вменяется избыточная величина отставания сверх запаса времени -- именно она реально
    толкает дату сдачи, согласно той же формуле, по которой уже считается `shifts_project_finish`.
    Категория этапа определяется по последнему снимку его зоны: если есть неудовлетворённые
    количественные проверки -- «Недостаток техники», иначе если работа попадает в период
    погодного риска -- «Погода», иначе -- общая категория «Отставание по графику».
    """
    shifting = [s for s in report.stages if s.get("shifts_project_finish")]
    if report.shift_days <= 0 or not shifting:
        return {"available": False, "shift_days": report.shift_days, "categories": [], "method_note": ""}

    weather_stage_ids: set[str] = set()
    if ctx.site_latitude is not None and ctx.site_longitude is not None:
        weather_forecast = fetch_forecast(ctx.site_latitude, ctx.site_longitude)
        weather_report = evaluate_weather_risks(
            schedule=ctx.schedule, weather_rules=ctx.weather_rules, forecast=weather_forecast
        )
        weather_stage_ids = {p.stage_id for p in weather_report.risk_periods}

    totals: dict[str, int] = {}
    for stage in shifting:
        excess = max(0, stage["delay_days"] - stage["total_float_days"])
        if excess <= 0:
            continue
        if _latest_quantity_shortfalls_for_zone(stage["stage_id"], stage["zone_id"], site):
            category = "missing_equipment"
        elif stage["stage_id"] in weather_stage_ids:
            category = "weather"
        else:
            category = "schedule_deviation"
        totals[category] = totals.get(category, 0) + excess

    total_days = sum(totals.values())
    categories = [
        {
            "key": key,
            "label_ru": _DELAY_CATEGORY_LABELS.get(key, key),
            "days": days,
            "share_percent": round((days / total_days) * 100) if total_days else 0,
        }
        for key, days in sorted(totals.items(), key=lambda kv: -kv[1])
    ]

    return {
        "available": bool(categories),
        "shift_days": report.shift_days,
        "categories": categories,
        "method_note": (
            "Оценка: для каждой работы, которая реально сдвигает срок сдачи, берётся избыток отставания "
            "сверх запаса времени и относится к причине по последнему снимку зоны (нехватка техники, "
            "погодный риск на период работы или прочее отставание по графику)."
        ),
    }


@router.get("/projects/{project_id}/schedule-network")
def get_project_schedule_network(site=Depends(get_project_site)) -> dict:
    """Сетевой график: критический путь, запас времени и сдвиг даты сдачи.

    Отвечает на вопрос, ради которого ведётся весь фотоконтроль: отстаёт ли
    объект от графика и на сколько дней сдвигается сдача.
    """
    ctx = get_context(site=site)
    report = schedule_network.build_report(
        ctx.schedule, datetime.now(UTC).date(), site=site
    )
    payload = schedule_network.to_dict(report)
    payload["schedule_is_demo"] = ctx.schedule.is_demo
    payload["delay_breakdown"] = _compute_delay_breakdown(report, ctx, site)
    return payload


@router.get("/projects/{project_id}/zones/{zone_id}/stages")
def get_project_zone_stages(zone_id: str, on_date: str | None = None, site=Depends(get_project_site)) -> dict:
    ctx = get_context(site=site)
    stages = ctx.schedule.stages_for_zone(zone_id)
    if on_date:
        try:
            day = date.fromisoformat(on_date)
        except ValueError as exc:
            raise HTTPException(400, "on_date должен быть в формате YYYY-MM-DD") from exc
        stages = [s for s in stages if s.is_active_on(day)]
    return {
        "zone_id": zone_id,
        "stages": [
            {
                "stage_id": s.stage_id,
                "work_name": s.work_name,
                "start_date": s.start_date.isoformat(),
                "end_date": s.end_date.isoformat(),
                "rule": (
                    {
                        "required": ctx.rules.stage_rules[s.stage_id].required,
                        "allowed": ctx.rules.stage_rules[s.stage_id].allowed,
                    }
                    if s.stage_id in ctx.rules.stage_rules
                    else None
                ),
            }
            for s in stages
        ],
    }


# --------------------------------------------------------------------------
# Этапы календарного плана (редактор графика) -- отдельно от `schedule-network`
# выше: тот отдаёт рассчитанный отчёт для просмотра, а эти -- дают редактору
# точечную CRUD-ручку над самими записями Stage/StageRule/StageRequiredItem.
# --------------------------------------------------------------------------


def _stage_to_dict(stage) -> dict:
    rule = getattr(stage, "rule", None)
    required_items = (
        list(rule.required_items.select_related("vocabulary_class").order_by("vocabulary_class__key"))
        if rule
        else []
    )
    return {
        "stage_id": stage.external_id,
        "work_code": stage.work_code,
        "work_name": stage.work_name,
        "zone_id": stage.zone.external_id,
        "zone_name": stage.zone.name,
        "start_date": stage.start_date.isoformat(),
        "end_date": stage.end_date.isoformat(),
        "parent_id": stage.parent.external_id if stage.parent_id else None,
        "predecessor_ids": sorted(p.external_id for p in stage.predecessors.all()),
        "technology_assumption": stage.technology_assumption,
        "required": [
            {
                "class_key": item.vocabulary_class.key,
                "label_ru": item.vocabulary_class.label_ru,
                "min_quantity": item.min_quantity,
            }
            for item in required_items
        ],
        "allowed": sorted(c.key for c in rule.allowed.all()) if rule else [],
        "alternatives_note": rule.alternatives_note if rule else "",
    }


@router.get("/projects/{project_id}/stages")
def list_project_stages(site=Depends(get_project_site)) -> dict:
    """Список этапов для редактора календарного плана -- доступен любому участнику проекта (просмотр)."""
    from core.models import Stage

    stages = (
        Stage.objects.filter(zone__site=site)
        .select_related("zone", "parent", "rule")
        .prefetch_related("predecessors", "rule__required_items__vocabulary_class", "rule__allowed")
        .order_by("start_date", "work_name")
    )
    return {"stages": [_stage_to_dict(s) for s in stages]}


class StageRequiredItemPayload(BaseModel):
    class_key: str
    min_quantity: int = Field(default=1, ge=1)


class StageWritePayload(BaseModel):
    work_name: str = Field(min_length=1, max_length=300)
    work_code: str = Field(default="", max_length=32)
    zone_id: str
    start_date: date
    end_date: date
    parent_id: str | None = None
    predecessor_ids: list[str] = Field(default_factory=list)
    technology_assumption: str = Field(default="", max_length=2000)
    required: list[StageRequiredItemPayload] = Field(default_factory=list)
    allowed: list[str] = Field(default_factory=list)
    alternatives_note: str = Field(default="", max_length=2000)


def _apply_stage_rule(stage, payload: StageWritePayload) -> None:
    """Создаёт/обновляет правило техники этапа целиком -- тот же принцип замены, что и в
    `_replace_frame_zones`: редактор присылает весь набор требований сразу, отслеживать частичные
    изменения на клиенте было бы сложнее без пользы.
    """
    from core.models import StageRequiredItem, StageRule, VocabularyClass

    class_keys = {item.class_key for item in payload.required} | set(payload.allowed)
    vocab_by_key = {c.key: c for c in VocabularyClass.objects.filter(key__in=class_keys)}
    missing = class_keys - set(vocab_by_key)
    if missing:
        raise HTTPException(400, f"Неизвестные классы техники: {sorted(missing)}")

    rule, _ = StageRule.objects.get_or_create(stage=stage)
    rule.alternatives_note = payload.alternatives_note.strip()
    rule.save(update_fields=["alternatives_note"])
    rule.allowed.set([vocab_by_key[key] for key in payload.allowed])
    StageRequiredItem.objects.filter(stage_rule=rule).delete()
    StageRequiredItem.objects.bulk_create(
        [
            StageRequiredItem(
                stage_rule=rule,
                vocabulary_class=vocab_by_key[item.class_key],
                min_quantity=item.min_quantity,
            )
            for item in payload.required
        ]
    )


@router.post("/projects/{project_id}/stages")
def create_project_stage(
    payload: StageWritePayload,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Создаёт новый этап календарного плана (только администратор)."""
    from django.db import transaction

    from core.models import Stage, Zone

    trimmed_name = payload.work_name.strip()
    if not trimmed_name:
        raise HTTPException(400, "Название этапа не может быть пустым")
    if payload.end_date < payload.start_date:
        raise HTTPException(400, "Дата окончания не может быть раньше даты начала")

    zone = Zone.objects.filter(external_id=payload.zone_id, site=site).first()
    if zone is None:
        raise HTTPException(404, "Зона не найдена в этом проекте")

    parent = None
    if payload.parent_id:
        parent = Stage.objects.filter(external_id=payload.parent_id, zone__site=site).first()
        if parent is None:
            raise HTTPException(404, "Родительский этап не найден в этом проекте")

    predecessors = list(Stage.objects.filter(external_id__in=payload.predecessor_ids, zone__site=site))
    missing_predecessors = set(payload.predecessor_ids) - {p.external_id for p in predecessors}
    if missing_predecessors:
        raise HTTPException(400, f"Предшественники не найдены в этом проекте: {sorted(missing_predecessors)}")

    index = Stage.objects.filter(zone__site=site).count() + 1
    external_id = f"site{site.pk}-stage-{index}"
    while Stage.objects.filter(external_id=external_id).exists():
        index += 1
        external_id = f"site{site.pk}-stage-{index}"

    with transaction.atomic():
        stage = Stage.objects.create(
            external_id=external_id,
            zone=zone,
            parent=parent,
            work_code=payload.work_code.strip(),
            work_name=trimmed_name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            technology_assumption=payload.technology_assumption.strip(),
            is_demo=False,
        )
        stage.predecessors.set(predecessors)
        _apply_stage_rule(stage, payload)

    return {"stage": _stage_to_dict(stage)}


@router.put("/projects/{project_id}/stages/{stage_id}")
def update_project_stage(
    stage_id: str,
    payload: StageWritePayload,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Обновляет этап целиком: даты, иерархию, предшественников и требуемую технику (только администратор)."""
    from django.db import transaction

    from core.models import Stage, Zone

    stage = Stage.objects.filter(external_id=stage_id, zone__site=site).first()
    if stage is None:
        raise HTTPException(404, "Этап не найден в этом проекте")

    trimmed_name = payload.work_name.strip()
    if not trimmed_name:
        raise HTTPException(400, "Название этапа не может быть пустым")
    if payload.end_date < payload.start_date:
        raise HTTPException(400, "Дата окончания не может быть раньше даты начала")

    zone = Zone.objects.filter(external_id=payload.zone_id, site=site).first()
    if zone is None:
        raise HTTPException(404, "Зона не найдена в этом проекте")

    parent = None
    if payload.parent_id:
        if payload.parent_id == stage_id:
            raise HTTPException(400, "Этап не может быть родителем самомому себе")
        parent = Stage.objects.filter(external_id=payload.parent_id, zone__site=site).first()
        if parent is None:
            raise HTTPException(404, "Родительский этап не найден в этом проекте")
        # Предотвращаем цикл: новый родитель не должен оказаться собственным потомком редактируемого этапа.
        cursor = parent
        while cursor is not None:
            if cursor.pk == stage.pk:
                raise HTTPException(400, "Нельзя сделать родителем собственного потомка — получится цикл")
            cursor = cursor.parent

    if stage_id in payload.predecessor_ids:
        raise HTTPException(400, "Этап не может быть предшественником самому себе")
    predecessors = list(Stage.objects.filter(external_id__in=payload.predecessor_ids, zone__site=site))
    missing_predecessors = set(payload.predecessor_ids) - {p.external_id for p in predecessors}
    if missing_predecessors:
        raise HTTPException(400, f"Предшественники не найдены в этом проекте: {sorted(missing_predecessors)}")

    with transaction.atomic():
        stage.zone = zone
        stage.parent = parent
        stage.work_code = payload.work_code.strip()
        stage.work_name = trimmed_name
        stage.start_date = payload.start_date
        stage.end_date = payload.end_date
        stage.technology_assumption = payload.technology_assumption.strip()
        stage.save(
            update_fields=[
                "zone",
                "parent",
                "work_code",
                "work_name",
                "start_date",
                "end_date",
                "technology_assumption",
            ]
        )
        stage.predecessors.set(predecessors)
        _apply_stage_rule(stage, payload)

    return {"stage": _stage_to_dict(stage)}


@router.delete("/projects/{project_id}/stages/{stage_id}")
def delete_project_stage(
    stage_id: str,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Удаляет этап, только если к нему ничего не привязано.

    Без этой проверки удаление этапа с вложенными работами каскадно стёрло бы их вместе с ним
    (Stage.parent -- CASCADE), а связи предшествования у других работ остались бы со ссылкой на несуществующий этап.
    """
    from core.models import Deviation, Stage, StageEvaluationRecord

    stage = Stage.objects.filter(external_id=stage_id, zone__site=site).first()
    if stage is None:
        raise HTTPException(404, "Этап не найден в этом проекте")

    child_count = Stage.objects.filter(parent=stage).count()
    successor_count = Stage.objects.filter(predecessors=stage).count()
    evaluation_count = StageEvaluationRecord.objects.filter(stage=stage).count()
    deviation_count = Deviation.objects.filter(stage=stage).count()
    if child_count or successor_count or evaluation_count or deviation_count:
        parts = []
        if child_count:
            parts.append(f"вложенных этапов: {child_count}")
        if successor_count:
            parts.append(f"этапов, где он указан предшественником: {successor_count}")
        if evaluation_count:
            parts.append(f"результатов проверки: {evaluation_count}")
        if deviation_count:
            parts.append(f"отклонений: {deviation_count}")
        raise HTTPException(
            400,
            "Нельзя удалить этап — с ним связаны данные ("
            + ", ".join(parts)
            + "). Сначала удалите или перенесите их.",
        )
    stage.delete()
    return {"status": "ok"}


@router.get("/projects/{project_id}/rules")
def get_project_rules(site=Depends(get_project_site)) -> dict:
    ctx = get_context(site=site)
    return {
        "ambiguity_margin": ctx.rules.ambiguity_margin,
        "stage_rules": {
            stage_id: {
                "work_name": rule.work_name,
                "required": rule.required,
                "required_quantities": rule.required_quantities,
                "allowed": rule.allowed,
                "alternatives_note": rule.alternatives_note,
            }
            for stage_id, rule in ctx.rules.stage_rules.items()
        },
        "confusable_class_pairs": ctx.rules.confusable_class_pairs,
        "known_limitations": [
            {
                "class_key": lim.class_key,
                "label_ru": lim.label_ru,
                "issue": lim.issue,
                "description": lim.description,
            }
            for lim in ctx.rules.known_limitations
        ],
    }


@router.get("/projects/{project_id}/weather-risks")
def get_project_weather_risks(site=Depends(get_project_site)) -> dict:
    ctx = get_context(site=site)
    if ctx.site_latitude is None or ctx.site_longitude is None:
        return {
            "status": "unavailable",
            "error": "У проекта не задано местоположение",
            "risk_periods": [],
        }
    forecast = fetch_forecast(ctx.site_latitude, ctx.site_longitude)
    report = evaluate_weather_risks(schedule=ctx.schedule, weather_rules=ctx.weather_rules, forecast=forecast)
    return {
        "status": report.status,
        "provider": report.provider,
        "latitude": report.latitude,
        "longitude": report.longitude,
        "fetched_at": report.fetched_at,
        "is_stale": report.is_stale,
        "error": report.error,
        "location_is_demo": False,
        "risk_periods": [
            {
                "stage_id": p.stage_id,
                "work_name": p.work_name,
                "factor": p.factor,
                "comparison": p.comparison,
                "threshold": p.threshold,
                "units": p.units,
                "start_time_utc": p.start_time_utc,
                "end_time_utc": p.end_time_utc,
                "peak_value": p.peak_value,
                "message": p.message,
            }
            for p in report.risk_periods
        ],
    }


@router.get("/projects/{project_id}/current-weather")
def get_project_current_weather(site=Depends(get_project_site)) -> dict:
    """Фактическая погода на объекте прямо сейчас + прогноз на несколько дней —
    для виджета в шапке интерфейса и его развёрнутого состояния при клике.

    Отдельно от `/weather-risks`: там прогноз на будущее для сравнения с графиком,
    здесь — текущие условия и общий прогноз. Отсутствие точки/границы у проекта —
    честный статус "no_location", а не подмена какой-то дефолтной точкой на карте.
    """
    if site.latitude is None or site.longitude is None:
        return {
            "status": "no_location",
            "address": site.address,
            "temperature": None,
            "weather_code": None,
            "description_ru": None,
            "wind_speed": None,
            "is_day": None,
            "fetched_at": None,
            "is_stale": True,
            "error": "У проекта не задано местоположение",
            "daily": [],
        }

    # Оба вызова -- блокирующие сетевые (свой timeout_seconds у каждого). Запускаем
    # их параллельно, а не последовательно -- иначе при недоступном API хуже случае
    # ответ ждёт двойной таймаут вместо одинарного.
    with ThreadPoolExecutor(max_workers=2) as pool:
        current_future = pool.submit(fetch_current_weather, site.latitude, site.longitude)
        daily_future = pool.submit(fetch_daily_forecast, site.latitude, site.longitude)
        result = current_future.result()
        daily_forecast = daily_future.result()
    return {
        "status": result.status,
        "address": site.address,
        "temperature": result.temperature_2m,
        "weather_code": result.weather_code,
        "description_ru": weather_code_label_ru(result.weather_code),
        "wind_speed": result.wind_speed_10m,
        "is_day": result.is_day,
        "fetched_at": result.fetched_at.isoformat() if result.fetched_at else None,
        "is_stale": result.is_stale,
        "error": result.error,
        "daily": [
            {
                "date": d.date,
                "weather_code": d.weather_code,
                "description_ru": weather_code_label_ru(d.weather_code),
                "temperature_max": d.temperature_max,
                "temperature_min": d.temperature_min,
                "precipitation_probability_max": d.precipitation_probability_max,
                "wind_speed_max": d.wind_speed_max,
            }
            for d in daily_forecast.days
        ]
        if daily_forecast.status == "ok"
        else [],
    }


class FrameZonePayload(BaseModel):
    """Одна зона на кадре в виде, в котором её присылает редактор."""

    name: str = Field(min_length=1, max_length=200)
    kind: str
    polygon: list[list[float]]
    stage_id: str | None = None
    note: str = ""


class FrameZonesUpdateRequest(BaseModel):
    """Редактор присылает весь набор зон целиком.

    Замена целиком проще и надёжнее частичных правок: пользователь рисует,
    двигает и удаляет полигоны в одном сеансе, и отслеживать каждое действие
    отдельным запросом значило бы усложнить и клиент, и сервер без пользы.
    """

    reference_width: int = Field(gt=0)
    reference_height: int = Field(gt=0)
    zones: list[FrameZonePayload]


def _frame_zone_to_dict(row) -> dict:
    return {
        "id": row.pk,
        "name": row.name,
        "kind": row.kind,
        "kind_label_ru": row.get_kind_display(),
        "polygon": row.polygon,
        "reference_width": row.reference_width,
        "reference_height": row.reference_height,
        "stage_id": row.stage.external_id if row.stage else None,
        "note": row.note,
    }


def _validate_frame_zone_payloads(payloads: list[FrameZonePayload]) -> None:
    """Общая проверка и для редактора зон (см. `replace_camera_frame_zones`), и для
    зон, заданных прямо при создании проекта (см. `create_project`).
    """
    from core.models import FrameZone

    valid_kinds = {key for key, _ in FrameZone.Kind.choices}
    for zone in payloads:
        if zone.kind not in valid_kinds:
            raise HTTPException(400, f"Недопустимый тип зоны: {zone.kind}")
        if len(zone.polygon) < 3:
            raise HTTPException(400, f"Зона «{zone.name}» содержит меньше трёх точек")
        if any(len(point) != 2 for point in zone.polygon):
            raise HTTPException(400, f"Зона «{zone.name}» содержит точку не из двух координат")


def _replace_frame_zones(
    camera, payloads: list[FrameZonePayload], reference_width: int, reference_height: int
) -> None:
    """Заменяет набор зон камеры целиком. Общая реализация для редактора зон и
    для формы создания проекта (там камера новая, и «замена» — это просто запись).
    """
    from django.db import transaction

    from core.models import FrameZone, Stage

    _validate_frame_zone_payloads(payloads)
    stages_by_id = {stage.external_id: stage for stage in Stage.objects.filter(zone=camera.zone)}

    with transaction.atomic():
        # Старые зоны удаляются, а не обновляются: ссылки на них из уже
        # сохранённых детекций обнуляются (SET_NULL), и это верное поведение:
        # прошлый анализ делался по старой разметке и переписывать его задним числом нельзя.
        FrameZone.objects.filter(camera=camera).delete()
        FrameZone.objects.bulk_create(
            [
                FrameZone(
                    camera=camera,
                    name=zone.name.strip(),
                    kind=zone.kind,
                    stage=stages_by_id.get(zone.stage_id) if zone.stage_id else None,
                    polygon=zone.polygon,
                    reference_width=reference_width,
                    reference_height=reference_height,
                    note=zone.note.strip(),
                )
                for zone in payloads
            ]
        )


@router.get("/projects/{project_id}/cameras/{camera_id}/frame-zones")
def get_camera_frame_zones(camera_id: str, site=Depends(get_project_site)) -> dict:
    """Зоны, размеченные на кадре камеры, и справочные данные для редактора."""
    from core.models import Camera, FrameZone, Stage

    camera = Camera.objects.filter(external_id=camera_id, zone__site=site).first()
    if camera is None:
        raise HTTPException(404, "Камера не найдена в этом проекте")

    rows = FrameZone.objects.filter(camera=camera).select_related("stage")
    stages = Stage.objects.filter(zone=camera.zone).order_by("start_date")
    return {
        "camera_id": camera.external_id,
        "camera_name": camera.name,
        "zone_id": camera.zone.external_id,
        "zones": [_frame_zone_to_dict(row) for row in rows],
        "kinds": [{"key": key, "label_ru": label} for key, label in FrameZone.Kind.choices],
        "stages": [
            {"stage_id": stage.external_id, "work_name": stage.work_name} for stage in stages
        ],
    }


@router.put("/projects/{project_id}/cameras/{camera_id}/frame-zones")
def replace_camera_frame_zones(
    camera_id: str,
    payload: FrameZonesUpdateRequest,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
    site=Depends(get_project_site),
) -> dict:
    """Заменяет набор зон камеры целиком (только администратор)."""
    from core.models import Camera, FrameZone

    camera = Camera.objects.filter(external_id=camera_id, zone__site=site).first()
    if camera is None:
        raise HTTPException(404, "Камера не найдена в этом проекте")

    _replace_frame_zones(camera, payload.zones, payload.reference_width, payload.reference_height)

    rows = FrameZone.objects.filter(camera=camera).select_related("stage")
    return {"zones": [_frame_zone_to_dict(row) for row in rows]}


@router.get("/projects/{project_id}/cameras/{camera_id}/reference-image")
def get_camera_reference_image(camera_id: str, site=Depends(get_project_site)) -> FileResponse:
    """Последний снимок камеры — подложка для редактора зон.

    Зоны рисуются поверх реального кадра, иначе инженер не понял бы, где
    именно проходит граница котлована или где стоянка.
    """
    from core.models import Camera, Observation

    camera = Camera.objects.filter(external_id=camera_id, zone__site=site).first()
    if camera is None:
        raise HTTPException(404, "Камера не найдена в этом проекте")

    observation = (
        Observation.objects.filter(camera=camera).order_by("-created_at").only("image_path").first()
    )
    if observation is None:
        raise HTTPException(
            404,
            "У камеры ещё нет ни одного снимка — загрузите кадр на экране анализа, "
            "чтобы разметить по нему зоны",
        )

    image_path = Path(observation.image_path).resolve()
    allowed_roots = (config.UPLOADS_DIR.resolve(), (config.DATA_DIR / "raw").resolve())
    if not image_path.is_file() or not any(image_path.is_relative_to(root) for root in allowed_roots):
        raise HTTPException(404, "Файл опорного снимка не найден на диске")

    response = FileResponse(image_path)
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _run_observation_pipeline(
    *,
    site,
    zone_id: str,
    observed_date: date | None,
    date_confirmed: bool,
    camera_id: str | None,
    image: UploadFile,
    require_zone_in_schedule: bool = True,
) -> dict:
    """Общее тело анализа снимка: детекция, сопоставление с графиком, сохранение,
    обогащение ИИ. Используется и одиночной загрузкой снимка (create_project_observation),
    и пакетной загрузкой фото при создании проекта (create_project).

    require_zone_in_schedule=False пропускает ранний защитный контроль "зона есть в
    графике" -- нужно для свежесозданного проекта без календарного плана: там у зоны
    честно нет ни одного этапа, и фото всё равно должно сохраниться в историю
    (evaluate_observation сам корректно отвечает "недостаточно данных" при отсутствии
    активных этапов).
    """
    ctx = get_context(site=site)
    if require_zone_in_schedule and not ctx.schedule.stages_for_zone(zone_id):
        raise HTTPException(404, f"Зона не найдена в графике проекта: {zone_id}")

    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(image.filename or "upload.jpg").suffix or ".jpg"
    observation_uuid = uuid.uuid4()
    observation_id = str(observation_uuid)
    dest_path = config.UPLOADS_DIR / f"{observation_id}{suffix}"

    hasher = hashlib.sha256()
    with dest_path.open("wb") as out:
        while chunk := image.file.read(1024 * 1024):
            hasher.update(chunk)
            out.write(chunk)
    image_sha256 = hasher.hexdigest()

    detector = get_detector()
    # Классификатор-корректор обучен только на коррекциях legacy-проекта -- не применяется
    # автоматически к новым проектам (см. план, граница AI Learning).
    detections = detector.detect(dest_path, apply_correction_classifier=site.is_legacy)

    image_size = _image_size(dest_path)
    observation_ai.apply_zones_and_activity(
        detections,
        camera_external_id=camera_id,
        image_size=image_size,
        observed_date=observed_date if date_confirmed else None,
    )

    evaluation = evaluate_observation(
        zone_id=zone_id,
        observed_date=observed_date,
        date_confirmed=bool(date_confirmed and observed_date is not None),
        detections=detections,
        schedule=ctx.schedule,
        rules=ctx.rules,
    )

    saved_to_db = persistence.persist_observation(
        observation_id=observation_uuid,
        zone_id=zone_id,
        image_path=str(dest_path),
        image_sha256=image_sha256,
        evaluation=evaluation,
        site=site,
        camera_external_id=camera_id,
        image_size=image_size,
    )

    critical_ids = schedule_network.critical_stage_ids(ctx.schedule)
    ai = observation_ai.enrich_observation(
        image_path=dest_path,
        image_sha256=image_sha256,
        zone_name=zone_id,
        evaluation=evaluation,
        schedule=ctx.schedule,
        uncovered_zones=frame_zones.uncovered_stage_zones(site=site),
        critical_stage_ids=critical_ids,
    )
    persistence.update_observation_vision(observation_uuid, ai.get("vision"))

    # Отклонения живут дольше снимка: одно и то же нарушение на соседних кадрах
    # должно остаться одной записью, а исчезнувшее -- закрыться этим же снимком.
    lifecycle = {"available": False, "opened": [], "repeated": [], "auto_resolved": []}
    if saved_to_db:
        findings = deviations_module.findings_from_evaluation(
            evaluation, critical_stage_ids=critical_ids
        )
        primary_stage_id = (
            evaluation.stage_evaluations[0].stage_id if evaluation.stage_evaluations else None
        )
        findings += deviations_module.findings_from_ai(ai, stage_id=primary_stage_id)
        lifecycle = deviations_module.sync_from_observation(
            observation_id=observation_uuid,
            zone_external_id=zone_id,
            site=site,
            findings=findings,
            observation_status=evaluation.overall_status,
            critical_stage_ids=critical_ids,
        )

    return {
        "observation_id": observation_id,
        "saved_to_db": saved_to_db,
        "ai": ai,
        "deviation_lifecycle": lifecycle,
        "image_sha256": image_sha256,
        "zone_id": evaluation.zone_id,
        "observed_date": evaluation.observed_date.isoformat() if evaluation.observed_date else None,
        "date_confirmed": evaluation.date_confirmed,
        "overall_status": evaluation.overall_status,
        "overall_status_label_ru": evaluation.overall_status_label_ru,
        "overall_explanation_ru": evaluation.overall_explanation_ru,
        "stages": [
            {
                "stage_id": e.stage_id,
                "work_name": e.work_name,
                "status": e.status,
                "status_label_ru": e.status_label_ru,
                "required": e.required,
                "allowed": e.allowed,
                "quantity_checks": [_quantity_check_to_dict(c) for c in e.quantity_checks],
                "missing_required": e.missing_required,
                "explanation_ru": e.explanation_ru,
                "unexpected_detections": [_detection_to_dict(d) for d in e.unexpected_detections],
                "ambiguous_detections": [_detection_to_dict(d) for d in e.ambiguous_detections],
                # Отклонение по критическому этапу и по этапу с запасом времени -- разные
                # по важности события, и интерфейс обязан их различать.
                "is_critical": e.stage_id in critical_ids,
            }
            for e in evaluation.stage_evaluations
        ],
        "detections": [_detection_to_dict(d) for d in evaluation.all_detections],
    }


@router.post("/projects/{project_id}/observations")
def create_project_observation(
    zone_id: str = Form(...),
    observed_date: str | None = Form(None),
    date_confirmed: bool = Form(False),
    camera_id: str | None = Form(None),
    image: UploadFile = File(...),
    site=Depends(get_project_site),
) -> dict:
    parsed_date: date | None = None
    if observed_date:
        try:
            parsed_date = date.fromisoformat(observed_date)
        except ValueError as exc:
            raise HTTPException(400, "observed_date должен быть в формате YYYY-MM-DD") from exc

    return _run_observation_pipeline(
        site=site,
        zone_id=zone_id,
        observed_date=parsed_date,
        date_confirmed=date_confirmed,
        camera_id=camera_id,
        image=image,
    )


@router.get("/projects/{project_id}/observations/{observation_id}/image")
def get_project_observation_image(observation_id: str, site=Depends(get_project_site)) -> FileResponse:
    image_path_str = persistence.get_observation_image_path(observation_id, site=site)
    if image_path_str is None:
        raise HTTPException(404, "Снимок не найден, недоступен в этом проекте или БД временно недоступна")

    image_path = Path(image_path_str).resolve()
    allowed_roots = (config.UPLOADS_DIR.resolve(), (config.DATA_DIR / "raw").resolve())
    if not image_path.is_file() or not any(image_path.is_relative_to(root) for root in allowed_roots):
        raise HTTPException(404, "Файл снимка не найден на диске")
    response = FileResponse(image_path)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/projects/{project_id}/observations/{observation_id}")
def get_project_observation(observation_id: str, site=Depends(get_project_site)) -> dict:
    result = persistence.get_observation(observation_id, site=site)
    if result is None:
        raise HTTPException(404, "Наблюдение не найдено, недоступно в этом проекте или БД временно недоступна")
    return result


class ProjectCorrectionCreateRequest(BaseModel):
    observation_id: str
    bbox: list[float]
    original_class_key: str
    original_confidence: float | None = None
    corrected_class_key: str | None = None


@router.post("/projects/{project_id}/corrections")
def create_project_correction(
    payload: ProjectCorrectionCreateRequest,
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
    site=Depends(get_project_site),
) -> dict:
    if len(payload.bbox) != 4:
        raise HTTPException(400, "bbox должен содержать 4 числа [x1, y1, x2, y2]")
    result = learning.save_correction(
        observation_id=payload.observation_id,
        bbox=payload.bbox,
        original_class_key=payload.original_class_key,
        original_confidence=payload.original_confidence,
        corrected_class_key=payload.corrected_class_key,
        user_id=current_user.id,
        site=site,
    )
    if result is None:
        raise HTTPException(
            404, "Наблюдение не найдено, недоступно в этом проекте, снимок недоступен или БД временно недоступна"
        )
    return {"correction": result}
