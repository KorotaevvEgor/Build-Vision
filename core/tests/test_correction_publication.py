import sys,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import ConstructionSite,ModelVersion,CorrectionTrainingRun
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import auth
from app.projects_router import router

class ProjectCorrectionPublicationTests(TransactionTestCase):
 def setUp(self):
  user=User.objects.create_user('publish-admin')
  self.user=SimpleNamespace(id=user.pk,username=user.username,role='admin')
  self.site=ConstructionSite.objects.create(name='Own');self.other=ConstructionSite.objects.create(name='Other')
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);artifact=self.root/'candidate.joblib';artifact.write_bytes(b'internal-training-artifact')
  self.patch=patch('app.config.MODELS_DIR',self.root);self.patch.start();self.addCleanup(self.patch.stop)
  self.version=ModelVersion.objects.create(site=self.site,version_label='test',trained_at=timezone.now(),artifact_path=str(artifact),metrics_json={'available':True,'split_unit':'observation','test_count':2,'accuracy':.9})
  CorrectionTrainingRun.objects.create(site=self.site,status='succeeded',model_version=self.version)
  api=FastAPI();api.include_router(router);api.dependency_overrides[auth.get_current_user]=lambda:self.user
  self.client=TestClient(api);self.addCleanup(self.client.close)
 def post(self,site=None):
  return self.client.post(f'/api/projects/{(site or self.site).pk}/correction-models/{self.version.pk}/activate')
 def test_publishes_only_own_version_and_preserves_other_production(self):
  previous=ModelVersion.objects.create(site=self.site,version_label='previous',status='production')
  foreign=ModelVersion.objects.create(site=self.other,version_label='foreign',status='production')
  response=self.post();self.assertEqual(response.status_code,200,response.text)
  previous.refresh_from_db();foreign.refresh_from_db();self.version.refresh_from_db()
  self.assertEqual(previous.status,'archived');self.assertEqual(foreign.status,'production');self.assertEqual(self.version.status,'production')
  self.assertEqual(self.post().status_code,200)
 def test_cross_project_and_non_admin_cannot_publish(self):
  self.assertEqual(self.post(self.other).status_code,404)
  self.user.role='participant'
  self.assertIn(self.post().status_code,[403,404])
  self.version.refresh_from_db();self.assertEqual(self.version.status,'candidate')
 def test_missing_validation_rejected_without_archiving_working_version(self):
  self.version.metrics_json={'available':False};self.version.save()
  previous=ModelVersion.objects.create(site=self.site,version_label='previous',status='production')
  self.assertEqual(self.post().status_code,422)
  previous.refresh_from_db();self.assertEqual(previous.status,'production')
