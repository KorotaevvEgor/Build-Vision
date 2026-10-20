from django.test import TransactionTestCase
from django.contrib.auth.models import User
from fastapi.testclient import TestClient
from backend.app.main import app
from core.models import ConstructionSite,Zone,Stage,UserProfile

class ScheduleV2Tests(TransactionTestCase):
 def setUp(self):
  user=User.objects.create_superuser("schedule_editor",password="Schedule!582409")
  UserProfile.objects.create(user=user,role="admin")
  self.site=ConstructionSite.objects.create(name="Schedule test",is_demo=False)
  self.zone=Zone.objects.create(site=self.site,external_id="s2-zone",name="Zone",geometry_geojson={"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]})
  self.a=Stage.objects.create(zone=self.zone,external_id="s2-a",work_name="A",start_date="2026-01-01",end_date="2026-01-02")
  self.b=Stage.objects.create(zone=self.zone,external_id="s2-b",work_name="B",start_date="2026-01-03",end_date="2026-01-04")
  self.b.predecessors.add(self.a)
  self.api=TestClient(app,base_url="https://testserver",headers={"X-BuildVision-Request":"1"});self.addCleanup(self.api.close)
  assert self.api.post("/api/auth/login",data={"username":"schedule_editor","password":"Schedule!582409"}).status_code==200
  self.url=f"/api/projects/{self.site.pk}/stages"
  self.payload={"work_name":"Changed","zone_id":self.zone.external_id,"start_date":"2026-01-01","end_date":"2026-01-05"}
 def test_cycle_is_rejected_without_writing(self):
  r=self.api.put(self.url+"/s2-a",json={**self.payload,"predecessor_ids":["s2-b"]})
  self.assertEqual(r.status_code,400)
  self.assertFalse(self.a.predecessors.exists())
 def test_update_persists_and_is_readable(self):
  self.assertEqual(self.api.put(self.url+"/s2-b",json=self.payload).status_code,200)
  self.b.refresh_from_db();self.assertEqual(self.b.work_name,"Changed")
  rows=self.api.get(self.url).json()["stages"]
  self.assertEqual(next(s for s in rows if s["stage_id"]=="s2-b")["end_date"],"2026-01-05")
 def test_invalid_dates_rejected(self):
  self.assertEqual(self.api.put(self.url+"/s2-a",json={**self.payload,"end_date":"2025-01-01"}).status_code,400)
 def test_participant_cannot_edit(self):
  u=User.objects.create_user("schedule_reader",password="Reader!582409");UserProfile.objects.create(user=u,role="participant")
  self.api.post("/api/auth/login",data={"username":"schedule_reader","password":"Reader!582409"})
  self.assertEqual(self.api.put(self.url+"/s2-a",json=self.payload).status_code,403)

 def test_create_and_delete_lifecycle(self):
  r=self.api.post(self.url,json=self.payload);self.assertEqual(r.status_code,200)
  sid=r.json()["stage"]["stage_id"]
  self.assertTrue(Stage.objects.filter(external_id=sid).exists())
  self.assertEqual(self.api.delete(self.url+"/"+sid).status_code,200)
  self.assertFalse(Stage.objects.filter(external_id=sid).exists())
 def test_referenced_stage_cannot_be_deleted(self):
  self.assertEqual(self.api.delete(self.url+"/s2-a").status_code,400)
  self.assertTrue(Stage.objects.filter(pk=self.a.pk).exists())
 def test_existing_cycle_can_be_repaired(self):
  self.a.predecessors.add(self.b)
  self.assertEqual(self.api.put(self.url+"/s2-a",json=self.payload).status_code,200)
  self.assertFalse(self.a.predecessors.exists())
 def test_foreign_project_predecessor_is_rejected(self):
  other=ConstructionSite.objects.create(name="Other")
  zone=Zone.objects.create(site=other,external_id="other-zone",name="Other",geometry_geojson={})
  Stage.objects.create(zone=zone,external_id="foreign",work_name="Foreign",start_date="2026-01-01",end_date="2026-01-02")
  self.assertEqual(self.api.post(self.url,json={**self.payload,"predecessor_ids":["foreign"]}).status_code,400)
