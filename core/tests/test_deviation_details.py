from datetime import date
import sys
from pathlib import Path
from django.test import TransactionTestCase
from core.models import ConstructionSite, Zone, Stage, Observation, StageEvaluationRecord, Deviation
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"backend"))
from app.deviations import get_deviation

class DeviationDetailsTests(TransactionTestCase):
    def setUp(self):
        self.a=ConstructionSite.objects.create(name="A")
        self.b=ConstructionSite.objects.create(name="B")
        self.za=Zone.objects.create(site=self.a,external_id="detail-a",name="A",geometry_geojson={})
        self.zb=Zone.objects.create(site=self.b,external_id="detail-b",name="B",geometry_geojson={})
        self.stage=Stage.objects.create(zone=self.za,external_id="detail-stage",work_name="Works",start_date=date(2026,1,1),end_date=date(2026,2,1))
        self.obs=Observation.objects.create(zone=self.za,image_path="test.jpg",image_sha256="a"*64,overall_status="possible_deviation",overall_explanation="Check")
        self.check={"class_key":"dump_truck","label_ru":"Самосвал","required_qty":6,"actual_qty":2,"satisfied":False}
        StageEvaluationRecord.objects.create(observation=self.obs,stage=self.stage,work_name_snapshot="Works",status="possible_deviation",explanation="Check",quantity_checks_snapshot=[self.check,{"class_key":"excavator","label_ru":"Экскаватор","required_qty":2,"actual_qty":2,"satisfied":True}])
        self.item=Deviation.objects.create(zone=self.za,stage=self.stage,kind="quantity_shortfall",severity="critical",title="Missing 999 in prose",message="Do not parse 999",equipment=["Самосвал"],signature="detail-test",first_observation=self.obs,last_observation=self.obs)
    def test_uses_snapshot_not_text_and_deduplicates_photos(self):
        data=get_deviation(deviation_id=self.item.pk,site=self.a)
        self.assertEqual(data["quantity_checks"],[self.check])
        self.assertEqual(len(data["evidence"]),1)
    def test_another_project_cannot_read_deviation(self):
        self.assertIsNone(get_deviation(deviation_id=self.item.pk,site=self.b))
    def test_missing_snapshot_is_not_invented(self):
        self.obs.stage_evaluations.all().delete()
        self.assertEqual(get_deviation(deviation_id=self.item.pk,site=self.a)["quantity_checks"],[])
    def test_mismatched_observation_zone_is_not_exposed(self):
        wrong=Observation.objects.create(zone=self.zb,image_path="private.jpg",image_sha256="b"*64,overall_status="possible_deviation",overall_explanation="Private")
        self.item.first_observation=wrong;self.item.last_observation=wrong;self.item.save()
        data=get_deviation(deviation_id=self.item.pk,site=self.a)
        self.assertEqual(data["quantity_checks"],[])
        self.assertEqual(data["evidence"],[])

    def test_http_route_keeps_project_boundary(self):
        from django.contrib.auth.models import User
        from core.models import UserProfile
        from fastapi.testclient import TestClient
        from app.main import app
        user=User.objects.create_superuser("detail-admin",password="test-password-only-123")
        UserProfile.objects.create(user=user,role="admin")
        with TestClient(app,base_url="https://testserver",headers={"X-BuildVision-Request":"1"}) as client:
            result=client.post("/api/auth/login",data={"username":user.username,"password":"test-password-only-123"})
            self.assertEqual(result.status_code,200,result.text)
            own=client.get(f"/api/projects/{self.a.pk}/deviations/{self.item.pk}")
            foreign=client.get(f"/api/projects/{self.b.pk}/deviations/{self.item.pk}")
            self.assertEqual(own.status_code,200,own.text)
            self.assertEqual(own.json()["quantity_checks"],[self.check])
            self.assertEqual(foreign.status_code,404)
            reviewed=client.post(f'/api/projects/{self.a.pk}/deviations/{self.item.pk}/review',json={'note':'Сверено с журналом смены'})
            self.assertEqual(reviewed.status_code,200,reviewed.text)
            self.item.refresh_from_db()
            self.assertEqual(self.item.engineering_review['reviewer_id'],user.pk)
            self.assertEqual(self.item.status,'detected')
            forbidden=client.post(f'/api/projects/{self.b.pk}/deviations/{self.item.pk}/review',json={'note':'Check'})
            self.assertEqual(forbidden.status_code,404)
            empty=client.post(f'/api/projects/{self.a.pk}/deviations/{self.item.pk}/status',json={'status':'resolved','note':''})
            self.assertEqual(empty.status_code,400)

    def test_evidence_contains_only_saved_observation_detections(self):
        from core.models import Camera, Detection
        camera=Camera.objects.create(zone=self.za,external_id="detail-cam",name="Камера 1",latitude=55,longitude=37)
        self.obs.camera=camera;self.obs.image_width=1000;self.obs.image_height=600;self.obs.save()
        detection=Detection.objects.create(observation=self.obs,class_key="dump_truck",label_ru="Самосвал",confidence=.87,bbox=[10,20,200,300])
        proof=get_deviation(deviation_id=self.item.pk,site=self.a)["evidence"][0]
        self.assertEqual((proof["image_width"],proof["image_height"]),(1000,600))
        self.assertEqual((proof["camera_id"],proof["camera_name"]),(camera.external_id,camera.name))
        self.assertEqual(proof["detections_source"],"observation")
        self.assertEqual(proof["detections"][0]["id"],detection.pk)
        self.assertEqual(proof["detections"][0]["bbox"],[10,20,200,300])
        self.obs.detections.all().delete()
        self.assertEqual(get_deviation(deviation_id=self.item.pk,site=self.a)["evidence"][0]["detections"],[])
