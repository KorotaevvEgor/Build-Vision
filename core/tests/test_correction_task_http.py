import sys
from pathlib import Path
from types import SimpleNamespace
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from core.models import ConstructionSite,ProjectMembership,Zone,Observation,CorrectionTask,VocabularyClass
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.correction_tasks import router
from app import auth

class CorrectionTaskHttpTests(TransactionTestCase):
 def setUp(self):
  user=User.objects.create_user('scoped-reviewer')
  self.user=SimpleNamespace(id=user.pk,username=user.username,role='participant')
  self.site=ConstructionSite.objects.create(name='Accessible');self.other=ConstructionSite.objects.create(name='Foreign')
  ProjectMembership.objects.create(site=self.site,user=user)
  zone=Zone.objects.create(site=self.other,external_id='foreign-review',name='Foreign',geometry_geojson={})
  self.foreign_obs=Observation.objects.create(zone=zone,image_path='missing.png',overall_status='insufficient_data')
  self.foreign_task=CorrectionTask.objects.create(site=self.other,observation=self.foreign_obs,title='Foreign task')
  own=Zone.objects.create(site=self.site,external_id='own-review',name='Own',geometry_geojson={})
  self.obs=Observation.objects.create(zone=own,image_path='missing.png',image_width=100,image_height=100,overall_status='insufficient_data')
  api=FastAPI();api.include_router(router);api.dependency_overrides[auth.get_current_user]=lambda:self.user
  self.client=TestClient(api);self.addCleanup(self.client.close)
  self.base=f'/api/projects/{self.site.pk}/correction-tasks'
 def test_cross_project_resources_cannot_be_read_or_mutated(self):
  self.assertEqual(self.client.get(self.base).status_code,200)
  self.assertEqual(self.client.get(f'/api/projects/{self.other.pk}/correction-tasks').status_code,404)
  self.assertEqual(self.client.get(f'{self.base}/{self.foreign_task.pk}').status_code,404)
  self.assertEqual(self.client.post(self.base,json={'observation_id':str(self.foreign_obs.pk)}).status_code,404)
 def test_member_can_take_and_save_but_cannot_start_training(self):
  task=self.client.post(self.base,json={'observation_id':str(self.obs.pk)}).json()['task']
  r=self.client.patch(f"{self.base}/{task['id']}",json={'revision':task['revision'],'status':'in_progress'})
  self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['task']['assignee_id'],self.user.id)
  r=self.client.patch(f"{self.base}/{task['id']}",json={'revision':r.json()['task']['revision'],'annotations':[{'id':'manual','bbox':[0,0,10,10],'corrected_class_key':[]} ]})
  self.assertEqual(r.status_code,422,r.text)
  self.assertEqual(self.client.post(self.base+'/train',json={'task_ids':[task['id']]}).status_code,403)
