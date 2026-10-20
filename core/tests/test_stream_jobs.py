import os,sys
from datetime import datetime,UTC,timedelta
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase,override_settings
from cryptography.fernet import Fernet
from core.models import ConstructionSite,Zone,Camera,CameraStreamConnection,StreamCapture
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app.streams.service import request_capture,claim_due_jobs,run_capture_job,schedule_due,worker_health
from app.streams.secrets import seal_source

class StreamJobsTests(TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,SK_STREAM_SECRET_KEY=Fernet.generate_key().decode());self.env.start();self.addCleanup(self.env.stop)
  self.site=ConstructionSite.objects.create(name='Streams');self.zone=Zone.objects.create(site=self.site,external_id='stream-zone',name='Zone',geometry_geojson={})
  self.camera=Camera.objects.create(zone=self.zone,external_id='stream-cam',name='Camera',latitude=55,longitude=37)
  self.conn=CameraStreamConnection.objects.create(camera=self.camera,source_ciphertext=seal_source('https://camera.example/live'),source_digest='x',weekdays=list(range(7)),enabled=True,next_capture_at=datetime.now(UTC)-timedelta(minutes=1))
 def test_disabled_and_scheduled_slots(self):
  self.conn.enabled=False;self.conn.save();schedule_due(datetime.now(UTC));self.assertEqual(StreamCapture.objects.count(),0)
  self.conn.enabled=True;self.conn.save();schedule_due(datetime.now(UTC));schedule_due(datetime.now(UTC));self.assertEqual(StreamCapture.objects.count(),1)
 def test_claim_and_revision(self):
  j=request_capture(self.conn,purpose='manual',actor=None)
  jobs=claim_due_jobs(datetime.now(UTC));self.assertEqual(len(jobs),1)
  self.assertEqual(claim_due_jobs(datetime.now(UTC)),[])
  self.conn.revision+=1;self.conn.save()
  with patch('app.streams.service.capture_frame') as cap:run_capture_job(jobs[0]);cap.assert_not_called()
  j.refresh_from_db();self.assertEqual(j.status,'skipped')
 def test_quota_and_no_online_url(self):
  self.conn.daily_limit=1;self.conn.save()
  StreamCapture.objects.create(connection=self.conn,camera=self.camera,scheduled_for=datetime.now(UTC),received_at=datetime.now(UTC),status='saved')
  with self.assertRaises(ValueError):request_capture(self.conn,purpose='manual',actor=None)
  self.assertFalse(worker_health(datetime.now(UTC))['available'])
 def test_duplicate_frame_does_not_keep_another_jpeg(self):
  from types import SimpleNamespace
  import tempfile
  self.conn.daily_limit=2;self.conn.save()
  StreamCapture.objects.create(connection=self.conn,camera=self.camera,scheduled_for=datetime.now(UTC),received_at=datetime.now(UTC),status='saved',sha256='same')
  job=request_capture(self.conn,purpose='manual',actor=None);claimed=claim_due_jobs(datetime.now(UTC))[0]
  with tempfile.TemporaryDirectory(dir='D:/dev/caches' if sys.platform=='win32' else None) as folder:
   def fake(source,*,destination):
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(b'jpeg')
    return SimpleNamespace(sha256='same',width=100,height=100,bytes=4,received_at=datetime.now(UTC))
   with patch('app.streams.service.config.UPLOADS_DIR',Path(folder)),patch('app.streams.service.validate_source',return_value=None),patch('app.streams.service.capture_frame',side_effect=fake):run_capture_job(claimed)
   self.assertEqual(list(Path(folder).rglob('*.jpg')),[])
  job.refresh_from_db();self.assertEqual(job.status,'duplicate');self.assertEqual(job.image_path,'')
 def test_expired_attempt_cannot_remove_replacement_image(self):
  from types import SimpleNamespace
  import tempfile,uuid
  job=request_capture(self.conn,purpose='manual',actor=None);claimed=claim_due_jobs(datetime.now(UTC))[0]
  with tempfile.TemporaryDirectory(dir='D:/dev/caches' if sys.platform=='win32' else None) as folder:
   replacement=Path(folder)/'replacement.jpg';replacement.write_bytes(b'new')
   def fake(source,*,destination):
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(b'old')
    StreamCapture.objects.filter(pk=job.pk).update(status='saved',lease_token=uuid.uuid4(),image_path=str(replacement))
    return SimpleNamespace(sha256='old',width=100,height=100,bytes=3,received_at=datetime.now(UTC))
   with patch('app.streams.service.config.UPLOADS_DIR',Path(folder)),patch('app.streams.service.validate_source',return_value=None),patch('app.streams.service.capture_frame',side_effect=fake):run_capture_job(claimed)
   self.assertEqual(replacement.read_bytes(),b'new');self.assertEqual(len(list(Path(folder).rglob('*.jpg'))),1)
