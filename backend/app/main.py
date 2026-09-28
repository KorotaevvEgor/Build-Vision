"""FastAPI-приложение СтройКонтроль: первый сквозной сценарий.

Снимок + зона + дата → детекция техники → правила по графику →
объяснимое предупреждение с доказательствами.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (
    auth,
    config,
    demo,
    frame_zones,
    insights,
    learning,
    observation_ai,
    persistence,
    project_scope,
    runtime_settings,
)
from . import forecast as forecast_module
from .app_context import get_context
from .detector import get_detector
from .matching import evaluate_observation
from .projects_router import router as projects_router
from .security import ApiRequestGuard
from .weather import fetch_forecast
from .weather_matching import evaluate_weather_risks

logger = logging.getLogger(__name__)

app = FastAPI(title="BuildVision API", version="0.1.0")

# Список разрешённых origin важен, когда авторизация идёт через cookie:
# с allow_origins=["*"] браузер не отправит credentials даже при allow_credentials=True.
# https://localhost — дефолтный origin WebView мобильного приложения (Capacitor Android,
# androidScheme="https", hostname="localhost" по умолчанию), см. mobile/.
_cors_origins = os.environ.get(
    "SK_CORS_ORIGINS",
    "http://localhost:5173,https://localhost",
).split(",")
app.add_middleware(ApiRequestGuard, allowed_origins=_cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(projects_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now(UTC).isoformat()}


# --------------------------------------------------------------------------
# Публичная демонстрация — единственная часть API без авторизации
# --------------------------------------------------------------------------


@app.get("/api/demo/samples")
def get_demo_samples() -> dict:
    """Готовые примеры для демонстрации без своего файла.

    Перечень готовится заранее скриптом вместе с прогревом кэша языковой
    модели: на защите ответ должен появляться сразу, а не через десять секунд.
    """
    return demo.list_samples()


@app.get("/api/demo/samples/{sample_id}/image")
def get_demo_sample_image(sample_id: str) -> FileResponse:
    path = demo.sample_image_path(sample_id)
    if path is None:
        raise HTTPException(404, "Пример не найден")
    return FileResponse(path)


@app.post("/api/demo/analyze")
def analyze_demo_image(request: Request, image: UploadFile = File(...)) -> dict:
    """Разбор одной фотографии без авторизации и без сохранения.

    Снимок удаляется сразу после разбора: публичный экран не должен накапливать
    чужие файлы на сервере.
    """
    client_key = request.client.host if request.client else "unknown"
    try:
        demo.check_rate_limit(client_key)
    except demo.RateLimited as exc:
        raise HTTPException(
            429,
            "Слишком много разборов с одного адреса. Попробуйте через "
            f"{exc.retry_after_seconds // 60 + 1} мин.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(400, "Ожидается изображение")

    try:
        path, digest = demo.save_temp_image(image.file, demo.safe_suffix(image.filename))
    except demo.TooLarge as exc:
        raise HTTPException(
            413, f"Файл больше {demo.MAX_IMAGE_BYTES // (1024 * 1024)} МБ"
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        return demo.analyze(path, digest)
    finally:
        path.unlink(missing_ok=True)


def _current_user_to_dict(user: auth.CurrentUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "role_label": user.role_label,
        "position": user.position,
        "display_position": user.display_position,
        "avatar_url": f"/api/auth/avatar/{user.id}" if user.has_avatar else None,
        "date_joined": user.date_joined,
        "last_login": user.last_login,
    }


@app.post("/api/auth/login")
def login(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    sessionid: str | None = Cookie(default=None),
) -> dict:
    """Проверяет логин/пароль через django.contrib.auth и ставит cookie сессии Django."""
    user = auth.authenticate_user(username, password)
    if user is None:
        raise HTTPException(401, "Неверный логин или пароль")
    session_key = auth.create_session(user, session_key=sessionid)
    auth.set_session_cookie(response, session_key)
    response.headers["Cache-Control"] = "no-store"
    return {"user": _current_user_to_dict(auth.user_to_current_user(user))}


@app.post("/api/auth/logout")
def logout(
    response: Response,
    sessionid: str | None = Cookie(default=None),
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> dict:
    if sessionid:
        auth.destroy_session(sessionid)
    auth.clear_session_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok"}


@app.get("/api/auth/me")
def get_me(
    response: Response, current_user: auth.CurrentUser = Depends(auth.get_current_user)
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"user": _current_user_to_dict(current_user)}


class ProfileUpdateRequest(BaseModel):
    position: str | None = None


@app.patch("/api/auth/profile")
def update_profile(
    payload: ProfileUpdateRequest,
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> dict:
    """Самообслуживание профиля: сейчас только должность — единственное текстовое поле без
    требований уникальности. ФИО/логин/email остаются зоной Django admin.
    """
    from .django_bridge import ensure_django_ready

    if not ensure_django_ready():
        raise HTTPException(503, "База данных недоступна — профиль не сохранён")

    from django.contrib.auth.models import User

    from core.models import UserProfile

    if payload.position is not None:
        profile, _ = UserProfile.objects.get_or_create(user_id=current_user.id)
        profile.position = payload.position.strip()[:150]
        profile.save(update_fields=["position"])

    user = User.objects.get(id=current_user.id)
    return {"user": _current_user_to_dict(auth.user_to_current_user(user))}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/auth/change-password")
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    sessionid: str | None = Cookie(default=None),
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> dict:
    """Смена пароля самим пользователем без принудительного выхода из текущей сессии."""
    from django.contrib.auth.models import User
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    user = User.objects.get(id=current_user.id)
    if not user.check_password(payload.current_password):
        raise HTTPException(400, "Текущий пароль указан неверно")

    try:
        validate_password(payload.new_password, user=user)
    except ValidationError as exc:
        raise HTTPException(400, " ".join(exc.messages)) from exc

    user.set_password(payload.new_password)
    user.save(update_fields=["password"])
    # Без этого get_user() сочтёт текущую сессию невалидной сразу же после смены
    # своего же пароля, и следующий запрос от того же браузера получил бы 401.
    auth.refresh_session_auth_hash(sessionid, user)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok"}


@app.post("/api/auth/sessions/logout-all")
def logout_all_sessions(
    response: Response,
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> dict:
    """Завершает все сессии пользователя, включая текущую — после этого нужен повторный вход."""
    removed = auth.end_all_sessions_for_user(current_user.id)
    auth.clear_session_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok", "sessions_ended": removed}


_AVATAR_MAX_BYTES = 5 * 1024 * 1024
_AVATAR_ALLOWED_SUFFIXES = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".webp": ".webp"}
_AVATARS_DIR = config.UPLOADS_DIR / "avatars"


def _avatar_path_for(user_id: int) -> Path | None:
    """Находит файл аватара на диске независимо от его расширения."""
    if not _AVATARS_DIR.is_dir():
        return None
    for suffix in set(_AVATAR_ALLOWED_SUFFIXES.values()):
        candidate = _AVATARS_DIR / f"{user_id}{suffix}"
        if candidate.is_file():
            return candidate
    return None


@app.get("/api/auth/avatar/{user_id}")
def get_avatar(
    user_id: int, current_user: auth.CurrentUser = Depends(auth.get_current_user)
) -> FileResponse:
    """Аватар любого пользователя доступен любому вошедшему — это не секретные данные."""
    path = _avatar_path_for(user_id)
    if path is None:
        raise HTTPException(404, "Аватар не загружен")
    response = FileResponse(path)
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


@app.post("/api/auth/avatar")
def upload_avatar(
    avatar: UploadFile = File(...),
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> dict:
    if avatar.content_type and not avatar.content_type.startswith("image/"):
        raise HTTPException(400, "Ожидается изображение")
    suffix = _AVATAR_ALLOWED_SUFFIXES.get(Path(avatar.filename or "").suffix.lower())
    if suffix is None:
        raise HTTPException(400, "Допустимы форматы: JPG, PNG, WebP")

    from .django_bridge import ensure_django_ready

    if not ensure_django_ready():
        raise HTTPException(503, "База данных недоступна — аватар не сохранён")

    from django.contrib.auth.models import User

    from core.models import UserProfile

    _AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    # Старый файл мог быть другого расширения — удаляем его, чтобы на диске не накапливались старые версии.
    existing = _avatar_path_for(current_user.id)
    if existing is not None:
        existing.unlink(missing_ok=True)

    dest_path = _AVATARS_DIR / f"{current_user.id}{suffix}"
    written = 0
    try:
        with dest_path.open("wb") as out:
            while chunk := avatar.file.read(256 * 1024):
                written += len(chunk)
                if written > _AVATAR_MAX_BYTES:
                    raise HTTPException(413, f"Файл больше {_AVATAR_MAX_BYTES // (1024 * 1024)} МБ")
                out.write(chunk)
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise
    if written == 0:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(400, "Пустой файл")

    profile, _ = UserProfile.objects.get_or_create(user_id=current_user.id)
    profile.avatar_path = str(dest_path)
    profile.save(update_fields=["avatar_path"])

    user = User.objects.get(id=current_user.id)
    return {"user": _current_user_to_dict(auth.user_to_current_user(user))}


@app.delete("/api/auth/avatar")
def delete_avatar(current_user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    from .django_bridge import ensure_django_ready

    if not ensure_django_ready():
        raise HTTPException(503, "База данных недоступна")

    from django.contrib.auth.models import User

    from core.models import UserProfile

    existing = _avatar_path_for(current_user.id)
    if existing is not None:
        existing.unlink(missing_ok=True)

    UserProfile.objects.filter(user_id=current_user.id).update(avatar_path="")

    user = User.objects.get(id=current_user.id)
    return {"user": _current_user_to_dict(auth.user_to_current_user(user))}


@app.get("/api/site")
def get_site(current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access)) -> dict:
    """Геометрия площадки и зон + список этапов графика (для страницы объекта)."""
    ctx = get_context()
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


@app.get("/api/dashboard")
def get_dashboard(current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access)) -> dict:
    """Сводка для Главной: счётчики, текущий этап, последние отклонения.

    В отличие от /api/site, эти данные не имеют файлового отката — это история
    реальных анализов в Postgres. При недоступной БД возвращается честный нулевой
    результат с `available: false`, а не выдуманные цифры.
    """
    ctx = get_context()
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
    )


@app.get("/api/cameras")
def get_cameras(current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access)) -> dict:
    return {"cameras": insights.list_cameras()}


@app.get("/api/cameras/{camera_id}")
def get_camera_detail(
    camera_id: str, current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access)
) -> dict:
    camera = insights.get_camera(camera_id)
    if camera is None:
        raise HTTPException(404, "Камера не найдена или БД недоступна")
    return camera


@app.get("/api/timeline")
def get_timeline(
    zone_id: str | None = None,
    days: int = 14,
    current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access),
) -> dict:
    return insights.timeline(zone_id, days=days)


@app.get("/api/analytics")
def get_analytics(
    days: int = 14, current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access)
) -> dict:
    return insights.analytics(days=days)


@app.get("/api/notifications")
def get_notifications(
    limit: int = 20, current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access)
) -> dict:
    return insights.notifications(limit=limit)


@app.get("/api/forecast")
def get_forecast(
    zone_id: str | None = None,
    current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access),
) -> dict:
    """Прогноз сроков для текущего активного этапа (зоны, если указана, иначе первого подходящего).

    Расчётный движок на реальных данных, без ML-предсказания и без LLM (см. forecast.py).
    """
    ctx = get_context()
    today = datetime.now(UTC).date()
    stages = ctx.schedule.stages
    if zone_id:
        stages = [s for s in stages if s.zone_id == zone_id]
    active = [s for s in stages if s.is_active_on(today)]
    if not active:
        return {"available": False, "reason": "Нет активного этапа для прогноза на сегодня"}

    stage = min(active, key=lambda s: s.start_date)
    result = forecast_module.forecast_for_stage(
        stage=stage,
        schedule=ctx.schedule,
        weather_rules=ctx.weather_rules,
        latitude=ctx.site_latitude,
        longitude=ctx.site_longitude,
        today=today,
    )
    result["available"] = True
    return result


@app.get("/api/zones/{zone_id}/stages")
def get_zone_stages(
    zone_id: str,
    on_date: str | None = None,
    current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access),
) -> dict:
    """Этапы зоны; если передан on_date (YYYY-MM-DD) — только активные на эту дату."""
    ctx = get_context()
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


@app.get("/api/weather-risks")
def get_weather_risks(
    current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access),
) -> dict:
    """Прогноз на ближайшие часы, пересечённый с этапами графика.

    Не блокирует анализ снимков; при недоступности API возвращает
    честный статус "unavailable", а не «рисков нет».
    """
    ctx = get_context()
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
        "location_is_demo": True,
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


class SettingsUpdateRequest(BaseModel):
    detector_confidence: float | None = None
    autolabel_min_vlm_confidence: str | None = None


def _settings_payload() -> dict:
    current = runtime_settings.load()
    return {
        "detector_confidence": current.detector_confidence,
        "autolabel_min_vlm_confidence": current.autolabel_min_vlm_confidence,
        "ambiguity_margin": current.ambiguity_margin,
        "stored_in_database": current.from_database,
        "detector_confidence_min": 0.05,
        "detector_confidence_max": 0.95,
        "vlm_confidence_choices": [
            {"key": "high", "label_ru": "Только высокая"},
            {"key": "medium", "label_ru": "Высокая и средняя"},
            {"key": "low", "label_ru": "Любая"},
        ],
    }


@app.get("/api/settings")
def get_settings(current_user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    """Текущие пороги. Читать может любой вошедший: от них зависит трактовка результата."""
    return _settings_payload()


@app.put("/api/settings")
def update_settings(
    payload: SettingsUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: auth.CurrentUser = Depends(auth.require_admin),
) -> dict:
    """Меняет пороги без перезапуска сервиса (только администратор)."""
    from .django_bridge import ensure_django_ready

    if not ensure_django_ready():
        raise HTTPException(503, "База данных недоступна — настройки не сохранены")

    from core.models import MatchingSettings

    row = MatchingSettings.get_solo()
    confidence_changed = False

    if payload.detector_confidence is not None:
        value = float(payload.detector_confidence)
        if not 0.05 <= value <= 0.95:
            raise HTTPException(400, "Порог уверенности должен быть в диапазоне 0.05-0.95")
        confidence_changed = value != row.detector_confidence
        row.detector_confidence = value

    if payload.autolabel_min_vlm_confidence is not None:
        allowed = {choice for choice, _ in MatchingSettings.VlmConfidence.choices}
        if payload.autolabel_min_vlm_confidence not in allowed:
            raise HTTPException(400, f"Допустимые значения: {', '.join(sorted(allowed))}")
        row.autolabel_min_vlm_confidence = payload.autolabel_min_vlm_confidence

    row.save()

    if confidence_changed:
        # Старые снимки должны получить актуальные детекции по новому порогу, а не ждать
        # случайной следующей загрузки фото по той же камере. Фоновая задача выполняется
        # после ответа, чтобы PUT не блокировался на время переанализа всей истории.
        from . import reanalysis

        background_tasks.add_task(reanalysis.reanalyze_all_observations)

    return _settings_payload()


@app.get("/api/vocabulary")
def get_vocabulary(current_user: auth.CurrentUser = Depends(auth.get_current_user)) -> dict:
    """Список классов техники из таксономии — для выбора правильного класса в контроле «Что это?»."""
    detector = get_detector()
    return {
        "classes": [
            {"key": info.key, "label_ru": info.label_ru}
            for info in sorted(detector.vocabulary.classes.values(), key=lambda c: c.label_ru)
            if info.in_taxonomy
        ]
    }


@app.get("/api/rules")
def get_rules(current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access)) -> dict:
    ctx = get_context()
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


def _detection_to_dict(detection) -> dict:
    return {
        "class_key": detection.class_key,
        "label_ru": detection.label_ru,
        "in_taxonomy": detection.in_taxonomy,
        "confidence": detection.confidence,
        "bbox": detection.bbox,
        "ambiguous": detection.ambiguous,
        "runner_up_class_key": detection.runner_up_class_key,
        "frame_zone_name": detection.frame_zone_name or None,
        "frame_zone_kind": detection.frame_zone_kind or None,
        "activity": detection.activity,
        "activity_reason": detection.activity_reason or None,
    }


def _image_size(path: Path) -> tuple[int, int]:
    """Размер снимка нужен, чтобы пересчитать зоны под другое разрешение кадра."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        logger.warning("Не удалось прочитать размер снимка %s", path)
        return (0, 0)


def _quantity_check_to_dict(check) -> dict:
    return {
        "class_key": check.class_key,
        "label_ru": check.label_ru,
        "required_qty": check.required_qty,
        "actual_qty": check.actual_qty,
        "satisfied": check.satisfied,
    }


@app.post("/api/observations")
def create_observation(
    zone_id: str = Form(...),
    observed_date: str | None = Form(None),
    date_confirmed: bool = Form(False),
    camera_id: str | None = Form(None),
    image: UploadFile = File(...),
    current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access),
) -> dict:
    """Загрузить снимок и получить объяснимый результат проверки.

    observed_date — дата съёмки в формате YYYY-MM-DD, вносимая вручную или
    после подтверждения OCR-извлечения штампа (см. план, методика п.1).
    Без date_confirmed=true результат всегда «Недостаточно данных».
    """
    ctx = get_context()
    if not ctx.schedule.stages_for_zone(zone_id):
        raise HTTPException(404, f"Зона не найдена в графике: {zone_id}")

    parsed_date: date | None = None
    if observed_date:
        try:
            parsed_date = date.fromisoformat(observed_date)
        except ValueError as exc:
            raise HTTPException(400, "observed_date должен быть в формате YYYY-MM-DD") from exc

    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(image.filename or "upload.jpg").suffix or ".jpg"
    observation_uuid = uuid.uuid4()
    observation_id = str(observation_uuid)
    dest_path = config.UPLOADS_DIR / f"{observation_id}{suffix}"

    # Функция синхронная (не async def): Django ORM в get_context()/persistence.*
    # вызывает обычные синхронные запросы и запрещает вызов из async-контекста
    # без sync_to_async. FastAPI запускает синхронные endpoint'ы в пуле потоков,
    # так что это не блокирует другие запросы.
    hasher = hashlib.sha256()
    with dest_path.open("wb") as out:
        while chunk := image.file.read(1024 * 1024):
            hasher.update(chunk)
            out.write(chunk)
    image_sha256 = hasher.hexdigest()

    detector = get_detector()
    detections = detector.detect(dest_path)

    image_size = _image_size(dest_path)
    observation_ai.apply_zones_and_activity(
        detections,
        camera_external_id=camera_id,
        image_size=image_size,
        observed_date=parsed_date if date_confirmed else None,
    )

    evaluation = evaluate_observation(
        zone_id=zone_id,
        observed_date=parsed_date,
        date_confirmed=bool(date_confirmed and parsed_date is not None),
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
        camera_external_id=camera_id,
        image_size=image_size,
    )

    ai = observation_ai.enrich_observation(
        image_path=dest_path,
        image_sha256=image_sha256,
        zone_name=zone_id,
        evaluation=evaluation,
        schedule=ctx.schedule,
        uncovered_zones=frame_zones.uncovered_stage_zones(),
    )

    return {
        "observation_id": observation_id,
        "saved_to_db": saved_to_db,
        "ai": ai,
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
            }
            for e in evaluation.stage_evaluations
        ],
        "detections": [_detection_to_dict(d) for d in evaluation.all_detections],
    }


@app.get("/api/observations/{observation_id}/image")
def get_observation_image(
    observation_id: str,
    current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access),
) -> FileResponse:
    """Отдаёт файл снимка наблюдения — для отображения в интерфейсе (Главная, карточки камер)."""
    image_path_str = persistence.get_observation_image_path(observation_id)
    if image_path_str is None:
        raise HTTPException(404, "Снимок не найден или БД временно недоступна")

    image_path = Path(image_path_str).resolve()
    allowed_roots = (config.UPLOADS_DIR.resolve(), (config.DATA_DIR / "raw").resolve())
    if not image_path.is_file() or not any(
        image_path.is_relative_to(root) for root in allowed_roots
    ):
        raise HTTPException(404, "Файл снимка не найден на диске")
    response = FileResponse(image_path)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.get("/api/observations/{observation_id}")
def get_observation(
    observation_id: str,
    current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access),
) -> dict:
    """Читает ранее сохранённое наблюдение из PostgreSQL (те же данные, что видны в Django admin)."""
    result = persistence.get_observation(observation_id)
    if result is None:
        raise HTTPException(404, "Наблюдение не найдено или БД временно недоступна")
    return result


class CorrectionCreateRequest(BaseModel):
    observation_id: str
    bbox: list[float]
    original_class_key: str
    original_confidence: float | None = None
    corrected_class_key: str | None = None


@app.post("/api/corrections")
def create_correction(
    payload: CorrectionCreateRequest,
    current_user: auth.CurrentUser = Depends(project_scope.require_legacy_project_access),
) -> dict:
    """Контрол «Что это?» на неоднозначных/низкоуверенных детекциях (см. модуль «AI Learning»).

    Коррекция обрезает фрагмент уже сохранённого снимка наблюдения — поэтому требует
    saved_to_db=true на этапе анализа снимка.
    """
    if len(payload.bbox) != 4:
        raise HTTPException(400, "bbox должен содержать 4 числа [x1, y1, x2, y2]")
    result = learning.save_correction(
        observation_id=payload.observation_id,
        bbox=payload.bbox,
        original_class_key=payload.original_class_key,
        original_confidence=payload.original_confidence,
        corrected_class_key=payload.corrected_class_key,
        user_id=current_user.id,
    )
    if result is None:
        raise HTTPException(
            404, "Наблюдение не найдено, снимок недоступен или БД временно недоступна"
        )
    return {"correction": result}


@app.get("/api/learning/stats")
def get_learning_stats(current_user: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    """Счётчики для экрана «Центр обучения AI» (/system/learning, только администратор): реальные числа из КА, без выдумок."""
    return learning.learning_stats()


@app.get("/api/model-versions")
def get_model_versions(current_user: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    return learning.list_model_versions()


@app.post("/api/model-versions/train")
def train_model_version(current_user: auth.CurrentUser = Depends(auth.require_admin)) -> dict:
    """Запускает обучение классификатора-корректора в фоне (только Администратор)."""
    return learning.trigger_training()


@app.post("/api/model-versions/{version_id}/deploy")
def deploy_model_version(
    version_id: int, current_user: auth.CurrentUser = Depends(auth.require_admin)
) -> dict:
    """Переводит кандидата в production (только Администратор), прежнюю production-версию — в архив."""
    result = learning.deploy_version(version_id)
    if result is None:
        raise HTTPException(404, "Версия модели не найдена или БД недоступна")
    return {"version": result}


# Статический фронтенд (если собран, см. Dockerfile). В локальной разработке
# без сборки каталог отсутствует, и этот блок просто не регистрируется —
# фронтенд работает отдельно через `npm run dev` на своём порту.
_frontend_dist = Path(os.environ.get("SK_FRONTEND_DIST", "")) if os.environ.get("SK_FRONTEND_DIST") else None

if _frontend_dist and _frontend_dist.is_dir():
    assets_dir = _frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """SPA fallback: отдаёт файл, если он есть, иначе index.html для React Router.

        Зарегистрирован последним: все явные /api/* маршруты выше уже
        перехватывают запросы раньше, чем он будет вызван.
        """
        if full_path.startswith("api/"):
            raise HTTPException(404, "Не найдено")
        candidate = (_frontend_dist / full_path).resolve()
        if not candidate.is_relative_to(_frontend_dist.resolve()):
            raise HTTPException(404, "Не найдено")
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_frontend_dist / "index.html")
