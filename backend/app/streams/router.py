import hashlib, uuid
from datetime import datetime, time, UTC, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from django.db import transaction, IntegrityError
from .scheduling import StreamSchedule, next_slot, estimated_weekly_frames
from .source_policy import validate_source, validate_source_format, SourceError
from .secrets import seal_source, open_source, mask_source, cipher
from .. import auth, config
from ..project_scope import get_project_site
router = APIRouter(prefix='/api/projects/{project_id}/streams', tags=['Видеопотоки'])

class StreamPayload(BaseModel):
    camera_id: str
    source_url: str = Field(default='', max_length=2000)
    interval_minutes: int = Field(default=15, ge=1, le=1440, strict=True)
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    window_start: time | None = None
    window_end: time | None = None
    timezone: str = 'Europe/Moscow'
    daily_limit: int = Field(default=1440, ge=1, le=1440, strict=True)
    analyze_frames: bool = False
    enabled: bool = False
    revision: int | None = None

class TestPayload(BaseModel):
    camera_id: str
    source_url: str = Field(default='', max_length=2000)
STATUS = {'pending': 'В очереди', 'capturing': 'Получение кадра', 'saved': 'Кадр сохранён', 'analysis_pending': 'Ожидает анализа', 'analyzing': 'Анализируется', 'analyzed': 'Проанализирован', 'failed': 'Ошибка подключения', 'duplicate': 'Повтор изображения', 'skipped': 'Пропущен'}

def stamp(value):
    return value.isoformat() if value else None

def get_connection(site, identity):
    from core.models import CameraStreamConnection
    c = CameraStreamConnection.objects.select_related('camera__zone').filter(pk=identity, camera__zone__site=site).first()
    if not c:
        raise HTTPException(404, 'Подключение не найдено в проекте')
    return c

def get_capture(site, identity):
    from core.models import StreamCapture
    j = StreamCapture.objects.filter(pk=identity, camera__zone__site=site).first()
    if not j:
        raise HTTPException(404, 'Кадр не найден в проекте')
    return j

def capture_data(j, project_id):
    return {'id': str(j.pk), 'status': j.status, 'status_label': STATUS.get(j.status, j.status), 'purpose': j.purpose, 'scheduled_for': stamp(j.scheduled_for), 'received_at': stamp(j.received_at), 'width': j.width, 'height': j.height, 'error_code': j.error_code, 'error_message': j.error_message, 'observation_id': str(j.observation_id) if j.observation_id else None, 'image_url': f'/api/projects/{project_id}/streams/captures/{j.pk}/image' if j.image_path else None}

def connection_data(c):
    now = datetime.now(UTC)
    fresh = bool(c.enabled and c.last_success_at and (now - c.last_success_at < timedelta(minutes=max(c.interval_minutes * 2, 5))))
    return {'id': c.pk, 'camera_id': c.camera.external_id, 'camera_name': c.camera.name, 'zone_name': c.camera.zone.name, 'source_display': c.source_display, 'source_type': c.source_type, 'source_configured': bool(c.source_ciphertext), 'enabled': c.enabled, 'revision': c.revision, 'interval_minutes': c.interval_minutes, 'weekdays': c.weekdays, 'window_start': c.window_start.strftime('%H:%M') if c.window_start else None, 'window_end': c.window_end.strftime('%H:%M') if c.window_end else None, 'timezone': c.timezone, 'daily_limit': c.daily_limit, 'analyze_frames': c.analyze_frames, 'last_success_at': stamp(c.last_success_at), 'last_error': c.last_error, 'next_capture_at': stamp(c.next_capture_at) if c.enabled else None, 'status': 'paused' if not c.enabled else 'online' if fresh else 'error' if c.last_error else 'waiting', 'weekly_frames': estimated_weekly_frames(StreamSchedule(c.interval_minutes, tuple(c.weekdays), c.window_start, c.window_end, c.timezone, c.daily_limit), now.astimezone(ZoneInfo(c.timezone)).date() - timedelta(days=now.astimezone(ZoneInfo(c.timezone)).weekday()))}

@router.get('')
def list_streams(site=Depends(get_project_site)):
    from core.models import Camera, CameraStreamConnection
    from .service import worker_health
    try:
        cipher()
        ready = True
    except ValueError:
        ready = False
    return {'items': [connection_data(c) for c in CameraStreamConnection.objects.select_related('camera__zone').filter(camera__zone__site=site)], 'cameras': [{'camera_id': c.external_id, 'name': c.name, 'zone_name': c.zone.name} for c in Camera.objects.select_related('zone').filter(zone__site=site)], 'worker': worker_health(datetime.now(UTC)), 'configured': ready}

def save(payload, site, actor, identity=None):
    from core.models import Camera, CameraStreamConnection, StreamCapture
    camera = Camera.objects.select_related('zone').filter(external_id=payload.camera_id, zone__site=site).first()
    if not camera:
        raise HTTPException(404, 'Камера не найдена в проекте')
    try:
        StreamSchedule(payload.interval_minutes, tuple(payload.weekdays), payload.window_start, payload.window_end, payload.timezone, payload.daily_limit)
    except (ValueError, KeyError):
        raise HTTPException(400, 'Проверьте интервал, дни, часы и часовой пояс') from None
    with transaction.atomic():
        Camera.objects.select_for_update().get(pk=camera.pk)
        c = get_connection(site, identity) if identity else CameraStreamConnection(camera=camera)
        if identity:
            c = CameraStreamConnection.objects.select_for_update().get(pk=c.pk)
            if payload.revision != c.revision:
                raise HTTPException(409, 'Настройки изменены. Обновите список и повторите действие.')
            if c.camera_id != camera.pk:
                raise HTTPException(400, 'Для другой камеры создайте отдельное подключение')
        elif CameraStreamConnection.objects.filter(camera=camera).exists():
            raise HTTPException(409, 'Для этой камеры уже настроен поток')
        try:
            url = payload.source_url.strip() or (open_source(c.source_ciphertext) if c.source_ciphertext else '')
            validate_source_format(url)
            encrypted = seal_source(url)
        except (SourceError, ValueError) as e:
            raise HTTPException(400, str(e)) from None
        digest = hashlib.sha256(url.encode()).hexdigest()
        now = datetime.now(UTC)
        proof = StreamCapture.objects.filter(camera=camera, purpose='test', source_digest=digest, status='saved', finished_at__gte=now - timedelta(hours=24)).order_by('-finished_at').first()
        if payload.enabled and (not proof):
            raise HTTPException(400, 'Сначала успешно проверьте текущий адрес потока')
        if c.source_digest != digest:
            c.last_success_at = None
        c.source_ciphertext = encrypted
        c.source_display = mask_source(url)
        c.source_digest = digest
        c.source_type = 'rtsp' if url.startswith('rtsp') else 'http'
        for key in ('interval_minutes', 'weekdays', 'window_start', 'window_end', 'timezone', 'daily_limit', 'analyze_frames', 'enabled'):
            setattr(c, key, getattr(payload, key))
        if identity:
            c.revision += 1
        if proof:
            c.last_test_at = proof.finished_at
            c.tested_source_digest = digest
        c.next_capture_at = next_slot(StreamSchedule(c.interval_minutes, tuple(c.weekdays), c.window_start, c.window_end, c.timezone, c.daily_limit), now) if c.enabled else None
        c.updated_by_id = actor.id
        if not identity:
            c.created_by_id = actor.id
        c.last_error = ''
        c.consecutive_failures = 0
        c.save()
        StreamCapture.objects.filter(connection=c, status__in=['pending', 'analysis_pending']).exclude(configuration_revision=c.revision).update(status='skipped')
        return {'connection': connection_data(c)}

@router.post('')
def create_stream(payload: StreamPayload, site=Depends(get_project_site), actor=Depends(auth.require_admin)):
    return save(payload, site, actor)

@router.patch('/{identity}')
def patch_stream(identity: int, payload: StreamPayload, site=Depends(get_project_site), actor=Depends(auth.require_admin)):
    return save(payload, site, actor, identity)

@router.post('/test')
def test_stream(payload: TestPayload, site=Depends(get_project_site), actor=Depends(auth.require_admin)):
    from core.models import Camera, CameraStreamConnection, StreamCapture
    from .service import worker_health
    if not worker_health(datetime.now(UTC))['available']:
        raise HTTPException(503, 'Обработчик видеопотоков недоступен. Настройки можно сохранить на паузе.')
    camera = Camera.objects.filter(external_id=payload.camera_id, zone__site=site).first()
    if not camera:
        raise HTTPException(404, 'Камера не найдена')
    now = datetime.now(UTC)
    with transaction.atomic():
        Camera.objects.select_for_update().get(pk=camera.pk)
        recent = StreamCapture.objects.filter(actor_id=actor.id, camera__zone__site=site, purpose='test', scheduled_for__gte=now - timedelta(minutes=5))
        if recent.count() >= 3 or recent.filter(status__in=['pending', 'capturing']).exists():
            raise HTTPException(429, 'Проверка уже выполняется или достигнут лимит: 3 проверки за 5 минут')
        try:
            url = payload.source_url.strip()
            if not url:
                c = CameraStreamConnection.objects.filter(camera=camera).first()
                url = open_source(c.source_ciphertext) if c else ''
            validate_source(url)
            encrypted = seal_source(url)
        except (ValueError, SourceError):
            raise HTTPException(400, 'Проверьте адрес потока и настройки разрешённых сетей сервера') from None
        j = StreamCapture.objects.create(camera=camera, actor_id=actor.id, purpose='test', source_ciphertext=encrypted, source_digest=hashlib.sha256(url.encode()).hexdigest(), scheduled_for=now)
    return {'capture': capture_data(j, site.pk)}

@router.get('/tests/{identity}')
def test_result(identity: uuid.UUID, site=Depends(get_project_site), actor=Depends(auth.require_admin)):
    j = get_capture(site, identity)
    if j.purpose != 'test':
        raise HTTPException(404, 'Проверка не найдена')
    return {'capture': capture_data(j, site.pk)}

@router.post('/{identity}/capture')
def capture_now(identity: int, site=Depends(get_project_site), actor=Depends(auth.require_admin)):
    from .service import worker_health, request_capture
    if not worker_health(datetime.now(UTC))['available']:
        raise HTTPException(503, 'Обработчик видеопотоков недоступен')
    c = get_connection(site, identity)
    try:
        j = request_capture(c, purpose='manual', actor=actor)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    return {'capture': capture_data(j, site.pk)}

@router.get('/{identity}/captures')
def captures(identity: int, offset: int=0, site=Depends(get_project_site)):
    from core.models import StreamCapture
    c = get_connection(site, identity)
    qs = StreamCapture.objects.filter(connection=c)
    offset = max(0, offset)
    return {'items': [capture_data(j, site.pk) for j in qs[offset:offset + 20]], 'total': qs.count()}

@router.get('/captures/{identity}/image')
def image(identity: uuid.UUID, site=Depends(get_project_site)):
    j = get_capture(site, identity)
    root = (config.UPLOADS_DIR / 'streams').resolve()
    path = Path(j.image_path).resolve() if j.image_path else root
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, 'Изображение недоступно')
    return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})

@router.post('/{identity}/captures/{capture_id}/analyze')
def analyze(identity: int, capture_id: uuid.UUID, site=Depends(get_project_site), actor=Depends(auth.require_admin)):
    from .service import worker_health, enqueue_capture_analysis
    c = get_connection(site, identity)
    j = get_capture(site, capture_id)
    if j.connection_id != c.pk:
        raise HTTPException(404, 'Кадр не принадлежит подключению')
    if not worker_health(datetime.now(UTC))['available']:
        raise HTTPException(503, 'Обработчик недоступен')
    try:
        enqueue_capture_analysis(j.pk)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    return {'queued': True}
