import os,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime,UTC
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from core.models import ConstructionSite,Zone,Camera,StreamWorkerHeartbeat,StreamCapture
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app import auth
from app.project_scope import get_project_site
from app.streams.router import router

class StreamApiTests(TransactionTestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,SK_STREAM_SECRET_KEY=Fernet.generate_key().decode());self.env.start();self.addCleanup(self.env.stop)
  u=User.objects.create(username='streamadmin',is_staff=True,is_superuser=True);self.actor=SimpleNamespace(id=u.pk,role='admin')
  self.site=ConstructionSite.objects.create(name='Stream API');z=Zone.objects.create(site=self.site,external_id='api-zone',name='Zone',geometry_geojson={});self.cam=Camera.objects.create(zone=z,external_id='api-camera',name='Camera',latitude=55,longitude=37)
  app=FastAPI();app.include_router(router);app.dependency_overrides[auth.require_admin]=lambda:self.actor;app.dependency_overrides[get_project_site]=lambda:self.site
  self.client=TestClient(app);self.path=f'/api/projects/{self.site.pk}/streams'
  self.payload={'camera_id':self.cam.external_id,'source_url':'https://camera.example/stream?token=secret','timezone':'Europe/Moscow'}
 def test_save_mask_and_revision(self):
  with patch('app.streams.router.validate_source'):
   r=self.client.post(self.path,json=self.payload)
  self.assertEqual(r.status_code,200,r.text);data=r.json()['connection'];self.assertNotIn('secret',r.text)
  r=self.client.patch(self.path+'/'+str(data['id']),json={**self.payload,'revision':99})
  self.assertEqual(r.status_code,409)
 def test_cannot_enable_without_test(self):
  with patch('app.streams.router.validate_source'):
   r=self.client.post(self.path,json={**self.payload,'enabled':True})
  self.assertEqual(r.status_code,400)
 def test_foreign_camera(self):
  r=self.client.post(self.path,json={**self.payload,'camera_id':'foreign'})
  self.assertEqual(r.status_code,404)


 def test_private_source_settings_save_without_worker_or_network(self):
  with patch('app.streams.router.validate_source',side_effect=AssertionError('Network validation must not run while saving')):
   r=self.client.post(self.path,json={**self.payload,'source_url':'rtsp://192.168.1.100:554/live','interval_minutes':30,'daily_limit':48})
  self.assertEqual(r.status_code,200,r.text)
  self.assertFalse(r.json()['connection']['enabled'])
