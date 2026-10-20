import sys
from datetime import date, timedelta
from pathlib import Path

from django.test import TestCase

from core.models import Camera, ConstructionSite, Observation, Zone

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import insights
from app.schedule import Schedule
from app.schedule import Stage as ScheduleStage


class CameraHistoryTests(TestCase):
    def test_paused_dashboard_uses_last_photo_and_latest_leaf_stage(self):
        site = ConstructionSite.objects.create(name="Приостановлен", status="paused")
        zone = Zone.objects.create(
            site=site, external_id="paused-zone", name="Площадка", geometry_geojson={}
        )
        Observation.objects.create(
            zone=zone,
            image_path="last.png",
            image_sha256="a" * 64,
            overall_status="insufficient_data",
            observed_date=date(2024, 6, 25),
            date_confirmed=True,
        )
        stages = [
            ScheduleStage(
                "earlier",
                "1",
                "Разработка котлована",
                zone.external_id,
                date(2024, 5, 27),
                date(2024, 6, 25),
                "",
                False,
            ),
            ScheduleStage(
                "last",
                "2",
                "Доработка котлована",
                zone.external_id,
                date(2024, 6, 25),
                date(2024, 6, 25),
                "",
                False,
            ),
        ]
        result = insights.dashboard_summary(
            schedule=Schedule(False, stages),
            zones=[],
            today=date(2026, 10, 16),
            site=site,
        )
        self.assertEqual(result["current_stage"]["stage_id"], "last")
        self.assertIsNone(result["current_stage"]["progress_percent"])
        self.assertEqual(result["reference_date"], "2024-06-25")
        self.assertEqual(result["project_status"], "paused")

    def test_camera_returns_the_ten_latest_observations(self):
        site = ConstructionSite.objects.create(name="История")
        zone = Zone.objects.create(
            site=site, external_id="history-zone", name="Площадка", geometry_geojson={}
        )
        camera = Camera.objects.create(
            zone=zone,
            external_id="history-camera",
            name="Обход",
            latitude=55,
            longitude=37,
        )
        rows = [
            Observation.objects.create(
                zone=zone,
                camera=camera,
                image_path=f"{i}.png",
                image_sha256=f"{i:064d}",
                overall_status="insufficient_data",
                observed_date=date(2024, 1, 1) + timedelta(days=i),
                date_confirmed=True,
            )
            for i in range(12)
        ]
        result = insights.get_camera(camera.external_id, site=site)
        self.assertEqual(
            [r["observation_id"] for r in result["recent_observations"]],
            [str(o.id) for o in reversed(rows[-10:])],
        )
