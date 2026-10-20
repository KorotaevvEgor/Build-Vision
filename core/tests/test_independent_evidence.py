import sys
from pathlib import Path
from datetime import date,datetime,timedelta,UTC
from django.test import TestCase
from core.models import ConstructionSite,Zone,Camera,Stage,Observation,StageEvaluationRecord,Deviation
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app.deviations import Finding,sync_from_observation

class IndependentEvidenceTests(TestCase):
    def setUp(self):
        self.site=ConstructionSite.objects.create(name='Proof')
        self.zone=Zone.objects.create(site=self.site,external_id='proof-zone',name='Zone',geometry_geojson={})
        self.camera=Camera.objects.create(zone=self.zone,external_id='proof-cam',name='Camera',latitude=55,longitude=37)
        self.stage=Stage.objects.create(zone=self.zone,external_id='proof-stage',work_name='Excavation',start_date=date(2026,1,1),end_date=date(2026,1,31))
    def observation(self,n,minutes=0,fingerprint='a'*64,status='possible_deviation'):
        obs=Observation.objects.create(zone=self.zone,camera=self.camera,image_path='proof.png',image_sha256=str(n)*64,
            observed_date=date(2026,1,10),date_confirmed=True,captured_at=datetime(2026,1,10,12,tzinfo=UTC)+timedelta(minutes=minutes),overall_status=status,overall_explanation='')
        StageEvaluationRecord.objects.create(observation=obs,stage=self.stage,status=status,work_name_snapshot='Excavation',explanation='',methodology_snapshot={'coverage_verified':True,'rule_fingerprint':fingerprint})
        return obs
    def sync(self,obs,present=True):
        return sync_from_observation(observation_id=obs.pk,zone_external_id=self.zone.external_id,site=self.site,observation_status=obs.overall_status,
            findings=[Finding(kind='quantity_shortfall',severity='warning',title='Missing',message='Check',stage_id=self.stage.external_id)] if present else [])
    def test_duplicate_file_does_not_strengthen_evidence(self):
        self.sync(self.observation(1));self.sync(self.observation(1,30))
        detail=Deviation.objects.get().evidence_records.all()
        self.assertEqual(sum(e.independent for e in detail),1)
    def test_two_timed_independent_frames_form_sequence(self):
        self.sync(self.observation(1));self.sync(self.observation(2,30))
        self.assertEqual(Deviation.objects.get().evidence_records.last().sequence_count,2)
    def test_changed_rule_and_other_camera_do_not_strengthen_original(self):
        self.sync(self.observation(1));self.sync(self.observation(2,30,fingerprint='b'*64))
        self.assertFalse(Deviation.objects.get().evidence_records.last().independent)
    def test_clean_frame_does_not_automatically_close(self):
        self.sync(self.observation(1));self.sync(self.observation(2,30,status='no_deviation'),False)
        self.assertEqual(Deviation.objects.get().status,'detected')
    def test_new_capture_too_close_does_not_strengthen(self):
        self.sync(self.observation(1));self.sync(self.observation(2,1))
        self.assertFalse(Deviation.objects.get().evidence_records.last().independent)

    def test_another_camera_cannot_strengthen_series(self):
        self.sync(self.observation(1))
        obs=self.observation(2,30)
        obs.camera=Camera.objects.create(zone=self.zone,external_id='proof-other',name='Other',latitude=55,longitude=37)
        obs.save()
        self.sync(obs)
        self.assertFalse(Deviation.objects.get().evidence_records.last().independent)

    def test_uncertain_frame_breaks_consecutive_series(self):
        self.sync(self.observation(1))
        self.sync(self.observation(2,20,status='insufficient_data'),False)
        self.sync(self.observation(3,40))
        self.assertEqual(Deviation.objects.get().evidence_records.last().sequence_count,1)

    def test_camera_of_another_zone_is_rejected_before_detector(self):
        from app.projects_router import _run_observation_pipeline
        from unittest.mock import patch
        from fastapi import HTTPException,UploadFile
        from io import BytesIO
        other=Zone.objects.create(site=self.site,external_id='other-zone',name='Other',geometry_geojson={})
        with patch('app.projects_router.get_context',return_value=None):
            with self.assertRaises(HTTPException) as error:
                _run_observation_pipeline(site=self.site,zone_id=other.external_id,observed_date=date(2026,1,10),date_confirmed=True,
                    camera_id=self.camera.external_id,image=UploadFile(filename='test.png',file=BytesIO(b'not-read')))
        self.assertEqual(error.exception.status_code,400)

    def test_activity_history_excludes_current_file_and_requires_spacing(self):
        from app.frame_zones import load_previous_frames
        from core.models import Detection
        zones=[{'id':1,'kind':'work','stage_id':None}]
        first=self.observation(1,0);close=self.observation(2,1);same=self.observation(3,20)
        for obs in [first,close,same]:
            StageEvaluationRecord.objects.filter(observation=obs).update(methodology_snapshot={'rule':{'frame_zones':zones}})
            Detection.objects.create(observation=obs,class_key='excavator',label_ru='Excavator',confidence=.9,bbox=[0,0,20,20],in_taxonomy=True)
        rows=load_previous_frames(self.camera.external_id,captured_at=datetime(2026,1,10,13,tzinfo=UTC),image_sha256=same.image_sha256,current_zones=zones)
        self.assertEqual(len(rows),1)
        self.assertEqual(load_previous_frames(self.camera.external_id,captured_at=datetime(2026,1,10,13,tzinfo=UTC),current_zones=[]),[])
