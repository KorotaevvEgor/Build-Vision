"""Persistent capture jobs. No decoding runs in an HTTP request."""
import hashlib,uuid
from datetime import datetime,UTC,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from django.db import transaction
from django.db.models import Q
from core.models import Camera,CameraStreamConnection,StreamCapture,StreamWorkerHeartbeat
from .scheduling import StreamSchedule,in_window,next_slot
from .secrets import open_source
from .source_policy import validate_source
from .capture import capture_frame,CaptureError
from .. import config

def schedule_for(c):return StreamSchedule(c.interval_minutes,tuple(c.weekdays),c.window_start,c.window_end,c.timezone,c.daily_limit)
def worker_health(now):
 h=StreamWorkerHeartbeat.objects.filter(key='capture').first()
 return {'available':bool(h and (now-h.updated_at).total_seconds()<60),'last_heartbeat_at':h.updated_at.isoformat() if h else None}
def quota_used(c,now):
 day=now.astimezone(ZoneInfo(c.timezone)).date()
 start=datetime.combine(day,datetime.min.time(),ZoneInfo(c.timezone)).astimezone(UTC)
 end=datetime.combine(day+timedelta(days=1),datetime.min.time(),ZoneInfo(c.timezone)).astimezone(UTC)
 return StreamCapture.objects.filter(connection=c,received_at__gte=start,received_at__lt=end,status__in=['saved','analysis_pending','analyzing','analyzed']).count()

def request_capture(connection,*,purpose,actor):
 now=datetime.now(UTC)
 with transaction.atomic():
  Camera.objects.select_for_update().get(pk=connection.camera_id)
  c=CameraStreamConnection.objects.select_for_update().get(pk=connection.pk)
  if quota_used(c,now)>=c.daily_limit:raise ValueError('Суточный лимит кадров достигнут')
  if StreamCapture.objects.filter(camera_id=c.camera_id,status__in=['pending','capturing']).exists():raise ValueError('Получение кадра уже запущено')
  return StreamCapture.objects.create(connection=c,camera_id=c.camera_id,actor_id=getattr(actor,'id',None),purpose=purpose,scheduled_for=now,configuration_revision=c.revision,source_ciphertext=c.source_ciphertext,source_digest=c.source_digest)

def schedule_due(now):
 candidates=list(CameraStreamConnection.objects.filter(enabled=True).filter(Q(next_capture_at__lte=now)|Q(next_capture_at=None)).values_list('pk','camera_id')[:50])
 for identity,camera_id in candidates:
  with transaction.atomic():
   if not Camera.objects.select_for_update(skip_locked=True).filter(pk=camera_id).first():continue
   c=CameraStreamConnection.objects.select_for_update().filter(pk=identity,enabled=True).first()
   if not c or (c.next_capture_at and c.next_capture_at>now):continue
   s=schedule_for(c)
   if quota_used(c,now)>=c.daily_limit:
    local=now.astimezone(ZoneInfo(c.timezone));tomorrow=datetime.combine(local.date()+timedelta(days=1),datetime.min.time(),ZoneInfo(c.timezone)).astimezone(UTC)
    c.next_capture_at=next_slot(s,tomorrow-timedelta(microseconds=1));c.save(update_fields=['next_capture_at']);continue
   if in_window(s,now) and quota_used(c,now)<c.daily_limit and not StreamCapture.objects.filter(camera_id=c.camera_id,status__in=['pending','capturing']).exists():
    slot=c.next_capture_at if c.next_capture_at and now-c.next_capture_at<timedelta(minutes=c.interval_minutes) else now.replace(second=0,microsecond=0)
    StreamCapture.objects.get_or_create(connection=c,scheduled_for=slot,purpose='scheduled',defaults={'camera_id':c.camera_id,'configuration_revision':c.revision,'source_ciphertext':c.source_ciphertext,'source_digest':c.source_digest})
   c.next_capture_at=next_slot(s,now);c.save(update_fields=['next_capture_at'])

def claim_due_jobs(now,*,limit=1):
 jobs=[]
 candidates=list(StreamCapture.objects.filter(Q(status='pending')|Q(status='capturing',lease_until__lt=now),scheduled_for__lte=now).order_by('scheduled_for').values_list('pk','camera_id')[:50])
 for identity,camera_id in candidates:
  with transaction.atomic():
   if not Camera.objects.select_for_update(skip_locked=True).filter(pk=camera_id).first():continue
   j=StreamCapture.objects.select_for_update().filter(pk=identity).first()
   if not j or (j.status!='pending' and not(j.status=='capturing' and j.lease_until<now)):continue
   if StreamCapture.objects.filter(camera_id=camera_id,status='capturing',lease_until__gt=now).exclude(pk=j.pk).exists():continue
   j.status='capturing';j.started_at=now;j.lease_until=now+timedelta(seconds=120);j.lease_token=uuid.uuid4();j.save()
   jobs.append(j)
   if len(jobs)>=limit:break
 return jobs

def is_current(j):
 if not j.connection_id:return j.purpose=='test'
 c=CameraStreamConnection.objects.filter(pk=j.connection_id).first()
 return bool(c and c.revision==j.configuration_revision and (c.enabled or j.purpose=='manual'))

def run_capture_job(job):
 j=StreamCapture.objects.get(pk=job.pk)
 if j.lease_token!=job.lease_token or j.status!='capturing':return
 if not is_current(j):
  StreamCapture.objects.filter(pk=j.pk,lease_token=job.lease_token).update(status='skipped',finished_at=datetime.now(UTC));return
 path=config.UPLOADS_DIR/'streams'/str(j.camera_id)/(str(j.pk)+'-'+str(job.lease_token)+'.jpg')
 try:
  frame=capture_frame(validate_source(open_source(j.source_ciphertext)),destination=path)
  now=datetime.now(UTC)
  with transaction.atomic():
   Camera.objects.select_for_update().get(pk=j.camera_id)
   c=CameraStreamConnection.objects.select_for_update().filter(pk=j.connection_id).first() if j.connection_id else None
   row=StreamCapture.objects.select_for_update().get(pk=j.pk)
   if row.status!='capturing' or row.lease_token!=job.lease_token or not is_current(row):
    path.unlink(missing_ok=True)
    if row.lease_token==job.lease_token:row.status='skipped';row.save(update_fields=['status'])
    return
   duplicate=row.purpose!='test' and StreamCapture.objects.filter(camera_id=row.camera_id,sha256=frame.sha256,status__in=['saved','analysis_pending','analyzing','analyzed','duplicate']).exists()
   row.status='duplicate' if duplicate else ('analysis_pending' if c and c.analyze_frames else 'saved')
   if row.purpose=='test':row.status='saved'

   if duplicate:path.unlink(missing_ok=True)
   row.image_path='' if duplicate else str(path);row.sha256=frame.sha256;row.width=frame.width;row.height=frame.height;row.size_bytes=frame.bytes;row.received_at=frame.received_at;row.finished_at=now;row.lease_until=None;row.save()
   if c:
    c.last_success_at=now;c.last_error='';c.consecutive_failures=0;c.save(update_fields=['last_success_at','last_error','consecutive_failures'])
 except Exception as exc:
  code=exc.code if isinstance(exc,CaptureError) else 'capture_failed';message=exc.public_message if isinstance(exc,CaptureError) else 'Не удалось получить кадр. Проверьте подключение камеры.'
  now=datetime.now(UTC)
  with transaction.atomic():
   Camera.objects.select_for_update().get(pk=j.camera_id)
   c=CameraStreamConnection.objects.select_for_update().filter(pk=j.connection_id).first() if j.connection_id else None
   row=StreamCapture.objects.select_for_update().get(pk=j.pk)
   if row.lease_token!=job.lease_token or row.status!='capturing':return
   row.status='failed';row.error_code=code;row.error_message=message;row.finished_at=now;row.lease_until=None;row.save()
   if row.connection_id:
    c.consecutive_failures+=1;c.last_error_at=now;c.last_error=message
    wait=[1,5,15][min(c.consecutive_failures-1,2)];candidate=now+timedelta(minutes=wait)
    c.next_capture_at=candidate if in_window(schedule_for(c),candidate) else next_slot(schedule_for(c),candidate)
    c.save(update_fields=['consecutive_failures','last_error_at','last_error','next_capture_at'])

def enqueue_capture_analysis(capture_id):
 with transaction.atomic():
  initial=StreamCapture.objects.get(pk=capture_id)
  Camera.objects.select_for_update().get(pk=initial.camera_id)
  j=StreamCapture.objects.select_for_update().get(pk=capture_id)
  if j.purpose=='test':raise ValueError('Пробный кадр не отправляется в журнал проекта')
  if j.status not in ('saved','analysis_pending'):raise ValueError('Кадр нельзя отправить на анализ в текущем состоянии')
  j.status='analysis_pending';j.analysis_explicit=True;j.save(update_fields=['status','analysis_explicit'])

def process_analysis_job():
 from ..observation_ingestion import ingest_observation
 now=datetime.now(UTC)
 with transaction.atomic():
  StreamCapture.objects.filter(status='analyzing',lease_until__lt=now).update(status='analysis_pending')
  candidate=StreamCapture.objects.filter(status='analysis_pending',scheduled_for__lte=now).order_by('scheduled_for').first()
  if not candidate:return False
  if not Camera.objects.select_for_update(skip_locked=True).filter(pk=candidate.camera_id).first():return False
  j=StreamCapture.objects.select_for_update().filter(pk=candidate.pk,status='analysis_pending').first()
  if not j:return False
  if not j.analysis_explicit and not is_current(j):j.status='skipped';j.save(update_fields=['status']);return True
  token=uuid.uuid4();j.lease_token=token;j.lease_until=now+timedelta(minutes=15);j.status='analyzing';j.analysis_attempts+=1;j.save()
 try:
  result=ingest_observation(site=j.camera.zone.site,zone_id=j.camera.zone.external_id,camera_id=j.camera.external_id,image_path=Path(j.image_path),capture_received_at=j.received_at,source_capture_id=j.pk)
  StreamCapture.objects.filter(pk=j.pk,lease_token=token).update(status='analyzed',observation_id=result['observation_id'],error_code='',error_message='',lease_until=None)
 except Exception:
  StreamCapture.objects.filter(pk=j.pk,lease_token=token).update(status='saved',error_code='analysis_failed',error_message='Кадр сохранён, анализ не завершён. Можно повторить отправку.',lease_until=None)
 return True

def clean_test_frames(now):
 root=(config.UPLOADS_DIR/'streams').resolve()
 for j in StreamCapture.objects.filter(purpose='test',scheduled_for__lt=now-timedelta(hours=24)).exclude(status__in=['capturing','pending'])[:100]:
  p=Path(j.image_path).resolve() if j.image_path else None
  if p and p.is_relative_to(root):p.unlink(missing_ok=True)
  j.delete()
