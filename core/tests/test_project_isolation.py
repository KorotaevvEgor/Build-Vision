"""Изоляция проектов: доступ, создание, legacy-совместимость, пустые проекты.

Реальные Django ORM/сессии + FastAPI через TestClient, на изолированной
тестовой БД (см. admin_panel/test_settings.py — SQLite in-memory, никогда
не подключается к production Postgres). Запускается только через
manage.py test (см. backend/tests/test_project_isolation_integration.py),
не напрямую через общий pytest-набор.
"""

import os
import sys
from pathlib import Path

from django.test import TransactionTestCase

from core.models import ConstructionSite, ProjectMembership, Stage, UserProfile, Zone

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

os.environ.setdefault("SK_CORS_ORIGINS", "https://testserver,https://localhost")
os.environ.setdefault("SK_SESSION_COOKIE_SECURE", "true")
os.environ.pop("SK_SESSION_COOKIE_DOMAIN", None)

from app.main import app
from django.contrib.auth.models import User
from fastapi.testclient import TestClient

BBOX_GEOMETRY = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}


class ProjectIsolationTests(TransactionTestCase):
    def setUp(self):
        self.password = "test-pass-not-real-12345"

        self.admin = User.objects.create_superuser("admin_iso", password=self.password)
        UserProfile.objects.create(user=self.admin, role=UserProfile.Role.ADMIN)

        self.member_a = User.objects.create_user("member_a_iso", password=self.password)
        UserProfile.objects.create(user=self.member_a, role=UserProfile.Role.PARTICIPANT)

        self.member_b = User.objects.create_user("member_b_iso", password=self.password)
        UserProfile.objects.create(user=self.member_b, role=UserProfile.Role.PARTICIPANT)

        self.outsider = User.objects.create_user("outsider_iso", password=self.password)
        UserProfile.objects.create(user=self.outsider, role=UserProfile.Role.PARTICIPANT)

        self.project_a = ConstructionSite.objects.create(name="Проект А", is_demo=False)
        self.project_b = ConstructionSite.objects.create(name="Проект Б", is_demo=False)
        ProjectMembership.objects.create(site=self.project_a, user=self.member_a)
        ProjectMembership.objects.create(site=self.project_b, user=self.member_b)

        self.zone_a = Zone.objects.create(
            site=self.project_a,
            external_id="zone-a-iso",
            name="Зона А",
            geometry_geojson=BBOX_GEOMETRY,
        )
        self.zone_b = Zone.objects.create(
            site=self.project_b,
            external_id="zone-b-iso",
            name="Зона Б",
            geometry_geojson=BBOX_GEOMETRY,
        )

        self.api = TestClient(
            app, base_url="https://testserver", headers={"X-BuildVision-Request": "1"}
        )
        self.addCleanup(self.api.close)

    def login(self, username):
        client = TestClient(
            app, base_url="https://testserver", headers={"X-BuildVision-Request": "1"}
        )
        self.addCleanup(client.close)
        result = client.post("/api/auth/login", data={"username": username, "password": self.password})
        assert result.status_code == 200, result.text
        return client

    # -- Список / видимость проектов -----------------------------------

    def test_admin_sees_all_projects(self):
        client = self.login("admin_iso")
        names = sorted(p["name"] for p in client.get("/api/projects").json()["projects"])
        self.assertEqual(names, ["Проект А", "Проект Б"])

    def test_participant_sees_only_assigned_projects(self):
        client = self.login("member_a_iso")
        names = [p["name"] for p in client.get("/api/projects").json()["projects"]]
        self.assertEqual(names, ["Проект А"])

    def test_participant_without_membership_sees_no_projects(self):
        client = self.login("outsider_iso")
        self.assertEqual(client.get("/api/projects").json()["projects"], [])

    # -- Доступ к чужому проекту -----------------------------------------

    def test_foreign_project_detail_is_404_not_403(self):
        client = self.login("member_a_iso")
        result = client.get(f"/api/projects/{self.project_b.pk}")
        self.assertEqual(result.status_code, 404)

    def test_nonexistent_project_is_404(self):
        client = self.login("admin_iso")
        result = client.get("/api/projects/999999")
        self.assertEqual(result.status_code, 404)

    def test_outsider_cannot_reach_any_scoped_endpoint(self):
        client = self.login("outsider_iso")
        for path in (
            f"/api/projects/{self.project_a.pk}/dashboard",
            f"/api/projects/{self.project_a.pk}/site",
            f"/api/projects/{self.project_a.pk}/cameras",
            f"/api/projects/{self.project_a.pk}/timeline",
            f"/api/projects/{self.project_a.pk}/analytics",
            f"/api/projects/{self.project_a.pk}/notifications",
            f"/api/projects/{self.project_a.pk}/forecast",
            f"/api/projects/{self.project_a.pk}/zones/zone-a-iso/stages",
            f"/api/projects/{self.project_a.pk}/weather-risks",
        ):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)

    def test_member_of_one_project_cannot_upload_to_other_projects_zone(self):
        """Чужая зона (из другого проекта) под своим project_id должна вернуть 404, не запись."""
        client = self.login("member_a_iso")
        result = client.post(
            f"/api/projects/{self.project_a.pk}/observations",
            data={"zone_id": "zone-b-iso"},
            files={"image": ("test.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")},
        )
        self.assertEqual(result.status_code, 404)

    def test_observation_and_image_not_reachable_through_foreign_project(self):
        admin_client = self.login("admin_iso")
        # Настраиваем минимальный этап, чтобы загрузка снимка прошла.
        Stage.objects.create(
            external_id="stage-a-iso",
            zone=self.zone_a,
            work_name="Тестовый этап",
            start_date="2020-01-01",
            end_date="2030-01-01",
        )
        from unittest.mock import patch

        with patch("app.projects_router.get_detector") as get_detector_mock:
            get_detector_mock.return_value.detect.return_value = []
            upload = admin_client.post(
                f"/api/projects/{self.project_a.pk}/observations",
                data={"zone_id": "zone-a-iso"},
                files={"image": ("test.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")},
            )
        self.assertEqual(upload.status_code, 200, upload.text)
        observation_id = upload.json()["observation_id"]

        # Владелец проекта видит наблюдение.
        own = admin_client.get(f"/api/projects/{self.project_a.pk}/observations/{observation_id}")
        self.assertEqual(own.status_code, 200)

        # Тот же ID через чужой project_id — явная ошибка, не подмена данных.
        foreign = admin_client.get(f"/api/projects/{self.project_b.pk}/observations/{observation_id}")
        self.assertEqual(foreign.status_code, 404)

        foreign_image = admin_client.get(
            f"/api/projects/{self.project_b.pk}/observations/{observation_id}/image"
        )
        self.assertEqual(foreign_image.status_code, 404)

    # -- Создание проекта --------------------------------------------------

    def test_only_admin_can_create_project(self):
        client = self.login("member_a_iso")
        result = client.post("/api/projects", json={"name": "Чужой проект"})
        self.assertEqual(result.status_code, 403)

    def test_admin_create_project_with_members_transactional(self):
        client = self.login("admin_iso")
        result = client.post(
            "/api/projects",
            json={
                "name": "Новый проект",
                "address": "ул. Строителей, 10",
                "status": "preparation",
                "member_user_ids": [self.member_b.id],
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        project_id = result.json()["project"]["project_id"]
        self.assertTrue(ProjectMembership.objects.filter(site_id=project_id, user=self.member_b).exists())

        # member_b теперь видит и старый (Проект Б), и новый проект.
        member_b_client = self.login("member_b_iso")
        names = sorted(p["name"] for p in member_b_client.get("/api/projects").json()["projects"])
        self.assertIn("Новый проект", names)
        self.assertIn("Проект Б", names)

    def test_create_project_rejects_invalid_status(self):
        client = self.login("admin_iso")
        result = client.post("/api/projects", json={"name": "X", "status": "not-a-real-status"})
        self.assertEqual(result.status_code, 400)

    def test_create_project_rejects_unknown_member_id(self):
        client = self.login("admin_iso")
        result = client.post("/api/projects", json={"name": "Y", "member_user_ids": [999999]})
        self.assertEqual(result.status_code, 400)
        self.assertFalse(ConstructionSite.objects.filter(name="Y").exists())

    # -- Пустой новый проект: без demo fallback -----------------------------

    def test_new_empty_project_has_no_demo_data(self):
        client = self.login("admin_iso")
        created = client.post("/api/projects", json={"name": "Пустой проект"}).json()["project"]
        project_id = created["project_id"]

        site_result = client.get(f"/api/projects/{project_id}/site").json()
        self.assertEqual(site_result["stages"], [])
        self.assertEqual(site_result["geojson"]["features"], [])

        dashboard_result = client.get(f"/api/projects/{project_id}/dashboard").json()
        self.assertEqual(dashboard_result["zone_count"], 0)
        self.assertEqual(dashboard_result["camera_count"], 0)
        self.assertEqual(dashboard_result["cameras"], [])

        cameras_result = client.get(f"/api/projects/{project_id}/cameras").json()
        self.assertEqual(cameras_result["cameras"], [])

    # -- Legacy-совместимость -------------------------------------------

    def test_legacy_endpoints_unavailable_without_pin(self):
        client = self.login("admin_iso")
        self.assertEqual(client.get("/api/site").status_code, 503)

    def test_legacy_endpoints_after_pin_respect_membership(self):
        self.project_a.is_legacy = True
        self.project_a.save(update_fields=["is_legacy"])

        admin_client = self.login("admin_iso")
        self.assertEqual(admin_client.get("/api/site").status_code, 200)

        member_a_client = self.login("member_a_iso")
        self.assertEqual(member_a_client.get("/api/site").status_code, 200)

        outsider_client = self.login("outsider_iso")
        self.assertEqual(outsider_client.get("/api/site").status_code, 403)

    def test_legacy_access_revocation_takes_effect_immediately(self):
        self.project_a.is_legacy = True
        self.project_a.save(update_fields=["is_legacy"])
        client = self.login("member_a_iso")
        self.assertEqual(client.get("/api/site").status_code, 200)

        ProjectMembership.objects.filter(site=self.project_a, user=self.member_a).delete()
        self.assertEqual(client.get("/api/site").status_code, 403)
