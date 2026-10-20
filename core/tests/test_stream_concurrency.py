import sys,os,threading
from pathlib import Path
from datetime import datetime,UTC
from unittest.mock import patch
from django.test import TransactionTestCase,skipUnlessDBFeature
from django.db import connection,connections
from django.contrib.auth.models import User
from cryptography.fernet import Fernet
from core.models import ConstructionSite,Zone,Camera,CameraStreamConnection,StreamCapture
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app.streams.service import request_capture,claim_due_jobs
from app.streams.router import save,StreamPayload
from app.streams.secrets import seal_source
from types import SimpleNamespace
class StreamConcurrencyTests(TransactionTestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,SK_STREAM_SECRET_KEY=Fernet.generate_key().decode());self.env.start();self.addCleanup(self.env.stop)
  u=User.objects.create(username='concurrent');self.actor=SimpleNamespace(id=u.pk)
  self.site=ConstructionSite.objects.create(name='Concurrent');z=Zone.objects.create(site=self.site,external_id='concurrent-zone',name='Zone',geometry_geojson={});c=Camera.objects.create(zone=z,external_id='concurrent-camera',name='Camera',latitude=55,longitude=37)
  self.conn=CameraStreamConnection.objects.create(camera=c,weekdays=list(range(7)),source_ciphertext=seal_source('https://camera.example/live'),source_digest='x')
 def parallel(self,left,right):
  barrier=threading.Barrier(2);errors=[]
  def run(fn):
   try:barrier.wait(timeout=3);fn()
   except ValueError:pass
   except Exception as e:errors.append(repr(e))
   finally:connections.close_all()
  threads=[threading.Thread(target=run,args=(f,)) for f in (left,right)]
  for t in threads:t.start()
  for t in threads:t.join(8)
  self.assertFalse(any(t.is_alive() for t in threads),'Database deadlock');self.assertEqual(errors,[])
 @skipUnlessDBFeature('has_select_for_update_skip_locked')
 def test_manual_capture_serializes_on_camera(self):
  self.parallel(lambda:request_capture(self.conn,purpose='manual',actor=self.actor),lambda:request_capture(self.conn,purpose='manual',actor=self.actor))
  self.assertEqual(StreamCapture.objects.filter(status='pending').count(),1)
 @skipUnlessDBFeature('has_select_for_update_skip_locked')
 def test_save_and_claim_do_not_deadlock(self):
  request_capture(self.conn,purpose='manual',actor=self.actor)
  payload=StreamPayload(camera_id=self.conn.camera.external_id,source_url='',revision=1)
  with patch('app.streams.router.validate_source'):
   self.parallel(lambda:save(payload,self.site,self.actor,self.conn.pk),lambda:claim_due_jobs(datetime.now(UTC)))
