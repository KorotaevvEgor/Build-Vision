import sys,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth.models import User
from core.models import ConstructionSite,Zone,Observation,Detection,VocabularyClass,CorrectionTask,Correction
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app import correction_tasks as tasks
from fastapi import HTTPException
from PIL import Image

class CorrectionTaskTests(TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.crop_patch=patch('app.learning.CORRECTIONS_DIR',Path(self.tmp.name)/'crops');self.crop_patch.start();self.addCleanup(self.crop_patch.stop)
  self.user=User.objects.create_user('reviewer');self.admin=SimpleNamespace(id=self.user.pk,username='reviewer',role='admin')
  self.site=ConstructionSite.objects.create(name='One');self.other=ConstructionSite.objects.create(name='Other')
  self.zone=Zone.objects.create(site=self.site,external_id='task-zone',name='Zone',geometry_geojson={})
  image=Path(self.tmp.name)/'image.png';Image.new('RGB',(100,80)).save(image)
  self.obs=Observation.objects.create(zone=self.zone,image_path=str(image),image_width=100,image_height=80,overall_status='insufficient_data')
  Detection.objects.create(observation=self.obs,class_key='excavator',label_ru='Экскаватор',confidence=.4,bbox=[10,10,40,50],ambiguous=True)
  VocabularyClass.objects.create(key='excavator',label_ru='Экскаватор',prompts=['excavator'])
 def create(self):return tasks.create_task(tasks.TaskCreate(observation_id=str(self.obs.pk)),site=self.site,current_user=self.admin)['task']
 def update(self,task,**kw):return tasks.update_task(task['id'],tasks.TaskUpdate(revision=task['revision'],**kw),site=self.site,current_user=self.admin)['task']
 def test_seed_is_idempotent_and_new_tasks_are_first(self):
  self.assertEqual(tasks.sync_tasks(site=self.site,current_user=self.admin)['created'],1)
  self.assertEqual(tasks.sync_tasks(site=self.site,current_user=self.admin)['created'],0)
  self.assertEqual(CorrectionTask.objects.count(),1)
 def test_take_save_and_ready_make_training_crops_without_rewriting_observation(self):
  task=self.update(self.create(),status='in_progress')
  self.assertEqual(task['assignee_id'],self.user.pk)
  annotations=task['annotations'];annotations[0]['corrected_class_key']='excavator'
  task=self.update(task,annotations=annotations,status='ready')
  self.assertEqual(task['status'],'ready');self.assertEqual(Correction.objects.count(),1)
  self.assertTrue(Path(Correction.objects.get().crop_image_path).is_file())
  self.assertEqual(self.obs.detections.get().confidence,.4)
 def test_ready_requires_decisions_and_bounds_are_checked(self):
  task=self.update(self.create(),status='in_progress')
  with self.assertRaises(HTTPException) as error:self.update(task,status='ready')
  self.assertEqual(error.exception.status_code,422)
  task['annotations'][0]['bbox']=[-2,0,40,50]
  with self.assertRaises(HTTPException):self.update(task,annotations=task['annotations'])
 def test_cross_project_and_stale_revision_are_rejected(self):
  task=self.create()
  with self.assertRaises(HTTPException) as error:tasks.task_detail(task['id'],site=self.other,current_user=self.admin)
  self.assertEqual(error.exception.status_code,404)
  self.update(task,status='in_progress')
  with self.assertRaises(HTTPException) as error:self.update(task,status='in_progress')
  self.assertEqual(error.exception.status_code,409)
 def test_manual_training_completion_is_forbidden(self):
  for state in ['training','trained']:
   with self.assertRaises(HTTPException):self.update(self.create(),status=state)
 def test_another_reviewer_cannot_edit_owned_draft(self):
  task=self.update(self.create(),status='in_progress')
  other=User.objects.create_user('other');member=SimpleNamespace(id=other.pk,username='other',role='participant')
  with self.assertRaises(HTTPException) as error:tasks.update_task(task['id'],tasks.TaskUpdate(revision=task['revision'],annotations=task['annotations']),site=self.site,current_user=member)
  self.assertEqual(error.exception.status_code,403)
 def test_project_candidate_cannot_be_deployed_as_global_model(self):
  from core.models import ModelVersion
  from app.learning import deploy_version
  candidate=ModelVersion.objects.create(site=self.site,version_label='project-v1',artifact_path='local.joblib')
  self.assertIsNone(deploy_version(candidate.pk))
  candidate.refresh_from_db();self.assertEqual(candidate.status,'candidate')
 def test_malformed_label_is_validation_error(self):
  task=self.update(self.create(),status='in_progress')
  for label in [[],{},4,True]:
   task['annotations'][0]['corrected_class_key']=label
   with self.assertRaises(HTTPException) as error:self.update(task,annotations=task['annotations'])
   self.assertEqual(error.exception.status_code,422)
 def test_non_taxonomy_labels_are_not_training_choices(self):
  VocabularyClass.objects.create(key='car',label_ru='Car',in_taxonomy=False)
  self.assertNotIn('car',[v['key'] for v in tasks._vocabulary()])
 def test_new_uncertain_observation_is_queued_automatically(self):
  self.assertTrue(tasks.enqueue_if_needed(self.obs.pk,self.site))
  self.assertFalse(tasks.enqueue_if_needed(self.obs.pk,self.site))
 def test_same_column_order_is_persisted(self):
  a=self.create()
  obs=Observation.objects.create(zone=self.zone,image_path=self.obs.image_path,image_width=100,image_height=80,overall_status='insufficient_data')
  b=tasks.create_task(tasks.TaskCreate(observation_id=str(obs.pk)),site=self.site,current_user=self.admin)['task']
  self.assertEqual([t.pk for t in tasks._tasks(self.site)],[b['id'],a['id']])
  self.update(a,before_id=b['id'])
  self.assertEqual([t.pk for t in tasks._tasks(self.site)],[a['id'],b['id']])
