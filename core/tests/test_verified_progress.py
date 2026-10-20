from datetime import date, timedelta
from types import SimpleNamespace

from django.test import TestCase, TransactionTestCase
from fastapi import HTTPException

from backend.app.projects_router import StageWritePayload, _validated_progress, _stage_to_dict
from backend.app.schedule import _load_schedule_from_db
from core.models import ConstructionSite, Stage, Zone


class VerifiedProgressTests(TestCase):
    def payload(self, **values):
        return StageWritePayload(work_name="Work", zone_id="z", start_date=date(2026, 1, 1), end_date=date(2026, 1, 10), **values)

    def test_incomplete_evidence_is_rejected(self):
        with self.assertRaises(HTTPException):
            _validated_progress(self.payload(verified_progress_percent=50), SimpleNamespace())

    def test_future_measurement_is_rejected(self):
        with self.assertRaises(HTTPException):
            _validated_progress(self.payload(verified_progress_percent=50, verified_progress_date=date.today()+timedelta(days=3), verified_progress_note="Volume measurement"), SimpleNamespace())

    def test_record_survives_orm_schedule_and_editor_serialization(self):
        site = ConstructionSite.objects.create(name="Progress")
        zone = Zone.objects.create(site=site, external_id="progress-zone", name="Zone", geometry_geojson={})
        fields = _validated_progress(self.payload(verified_progress_percent=50, verified_progress_date=date(2026, 1, 5), verified_progress_note="50 of 100 m3", expected_finish_date=date(2026, 1, 15)), site)
        row = Stage.objects.create(zone=zone, external_id="progress-work", work_name="Work", start_date=date(2026, 1, 1), end_date=date(2026, 1, 10), **fields)
        self.assertEqual(_stage_to_dict(row)["verified_progress_percent"], 50)
        work = _load_schedule_from_db(site).stages[0]
        self.assertEqual(work.expected_finish_date, date(2026, 1, 15))
        self.assertEqual(work.verified_progress_note, "50 of 100 m3")


class VerifiedProgressEndpointTests(TransactionTestCase):
    def test_editor_record_changes_network_scenario_and_full_progress_confirms_completion(self):
        from django.contrib.auth.models import User
        from fastapi.testclient import TestClient
        from backend.app.main import app
        from core.models import UserProfile

        user = User.objects.create_superuser("progress-editor", password="Progress!582409")
        UserProfile.objects.create(user=user, role="admin")
        site = ConstructionSite.objects.create(name="Measured site", is_demo=False)
        zone = Zone.objects.create(site=site, external_id="measured-zone", name="Zone", geometry_geojson={})
        Stage.objects.create(zone=zone, external_id="measured-stage", work_name="Work", start_date="2026-01-01", end_date="2026-01-10", is_demo=False)
        with TestClient(app, base_url="https://testserver", headers={"X-BuildVision-Request": "1"}) as client:
            self.assertEqual(client.post("/api/auth/login", data={"username": "progress-editor", "password": "Progress!582409"}).status_code, 200)
            url = f"/api/projects/{site.pk}/stages/measured-stage"
            payload = {"work_name": "Work", "zone_id": zone.external_id, "start_date": "2026-01-01", "end_date": "2026-01-10", "verified_progress_percent": 50, "verified_progress_date": "2026-01-05", "verified_progress_note": "Engineer measured 50 m3 of 100", "expected_finish_date": "2026-01-15", "project_timezone": "Europe/Moscow"}
            response = client.put(url, json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            report = client.get(f"/api/projects/{site.pk}/schedule-network?include_breakdown=false").json()
            self.assertEqual(report["projected_finish_date"], "2026-01-15")
            self.assertEqual(report["stages"][0]["estimate_kind"], "responsible_person_estimate")
            self.assertFalse(report["stages"][0]["completion_confirmed"])
            # Old clients editing plan fields must not erase confirmed progress.
            old_payload = {k: payload[k] for k in ("work_name", "zone_id", "start_date", "end_date")}
            self.assertEqual(client.put(url, json=old_payload).status_code, 200)
            self.assertEqual(Stage.objects.get(external_id="measured-stage").verified_progress_percent, 50)
            response = client.put(url, json={**payload, "verified_progress_percent": 100, "verified_progress_date": "2026-01-09", "expected_finish_date": None})
            self.assertEqual(response.status_code, 200, response.text)
            report = client.get(f"/api/projects/{site.pk}/schedule-network?include_breakdown=false").json()
            self.assertTrue(report["stages"][0]["completion_confirmed"])
            self.assertEqual(report["stages"][0]["state"], "done_on_time")
