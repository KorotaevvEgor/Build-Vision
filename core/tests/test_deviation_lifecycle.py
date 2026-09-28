"""Тесты жизненного цикла отклонения.

Проверяется главное обещание модуля: одно и то же нарушение на соседних
кадрах остаётся одной записью, исчезнувшее нарушение закрывается следующим
снимком автоматически, а кадр со статусом «недостаточно данных» ничего не
закрывает — он ничего и не доказывает.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app import deviations as deviations_module

from core.models import (
    ConstructionSite,
    Deviation,
    Observation,
    ProjectEvent,
    Stage,
    Zone,
)


def finding(kind: str = "missing_equipment", stage_id: str | None = "stage-x", equipment=("excavator",)):
    return deviations_module.Finding(
        kind=kind,
        severity="warning",
        title="Нет требуемой техники",
        message="Экскаватор не обнаружен.",
        equipment=list(equipment),
        stage_id=stage_id,
    )


class DeviationLifecycleTests(TestCase):
    def setUp(self) -> None:
        self.site = ConstructionSite.objects.create(name="Тестовая площадка", is_demo=True)
        self.zone = Zone.objects.create(
            site=self.site,
            external_id="zone-test",
            name="Тестовая зона",
            geometry_geojson={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
        )
        Stage.objects.create(
            external_id="stage-x",
            zone=self.zone,
            work_name="Тестовая работа",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

    def _observation(self, status: str = "possible_deviation") -> Observation:
        return Observation.objects.create(
            zone=self.zone,
            image_path="/tmp/x.png",
            image_sha256="0" * 64,
            overall_status=status,
            overall_explanation="",
        )

    def _sync(self, observation: Observation, findings, status: str = "possible_deviation") -> dict:
        return deviations_module.sync_from_observation(
            observation_id=observation.pk,
            zone_external_id=self.zone.external_id,
            site=self.site,
            findings=findings,
            observation_status=status,
        )

    def test_first_observation_opens_deviation_with_before_photo(self) -> None:
        observation = self._observation()
        result = self._sync(observation, [finding()])

        self.assertEqual(len(result["opened"]), 1)
        deviation = Deviation.objects.get()
        self.assertEqual(deviation.status, Deviation.Status.DETECTED)
        self.assertEqual(deviation.first_observation_id, observation.pk)
        self.assertEqual(deviation.occurrence_count, 1)
        self.assertTrue(
            ProjectEvent.objects.filter(kind=ProjectEvent.Kind.DEVIATION_DETECTED).exists()
        )

    def test_same_finding_on_next_frame_does_not_duplicate(self) -> None:
        self._sync(self._observation(), [finding()])
        second = self._observation()
        result = self._sync(second, [finding()])

        self.assertEqual(Deviation.objects.count(), 1)
        self.assertEqual(len(result["repeated"]), 1)
        deviation = Deviation.objects.get()
        self.assertEqual(deviation.occurrence_count, 2)
        self.assertEqual(deviation.last_observation_id, second.pk)

    def test_different_equipment_is_a_different_deviation(self) -> None:
        self._sync(self._observation(), [finding(equipment=("excavator",))])
        self._sync(self._observation(), [finding(equipment=("dump_truck",))])

        # Первое отклонение закрылось (техника уже другая), второе открылось.
        self.assertEqual(Deviation.objects.count(), 2)
        self.assertEqual(
            set(Deviation.objects.values_list("status", flat=True)),
            {Deviation.Status.RESOLVED, Deviation.Status.DETECTED},
        )

    def test_clean_next_frame_closes_deviation_and_attaches_after_photo(self) -> None:
        self._sync(self._observation(), [finding()])
        clean = self._observation(status="no_deviation")
        result = self._sync(clean, [], status="no_deviation")

        deviation = Deviation.objects.get()
        self.assertEqual(deviation.status, Deviation.Status.RESOLVED)
        self.assertTrue(deviation.auto_resolved)
        self.assertEqual(deviation.resolved_observation_id, clean.pk)
        self.assertEqual(len(result["auto_resolved"]), 1)
        self.assertTrue(
            ProjectEvent.objects.filter(kind=ProjectEvent.Kind.DEVIATION_AUTO_RESOLVED).exists()
        )

    def test_insufficient_data_frame_does_not_close_anything(self) -> None:
        """Снимок, по которому ничего не установлено, не доказывает устранения."""
        self._sync(self._observation(), [finding()])
        unclear = self._observation(status="insufficient_data")
        result = self._sync(unclear, [], status="insufficient_data")

        self.assertEqual(result["auto_resolved"], [])
        self.assertEqual(Deviation.objects.get().status, Deviation.Status.DETECTED)

    def test_uncovered_zone_is_not_closed_by_a_frame(self) -> None:
        """Непокрытая камерами зона — вопрос настройки, снимок её не закрывает."""
        self._sync(self._observation(), [finding(kind="zone_not_covered", stage_id=None, equipment=())])
        self._sync(self._observation(status="no_deviation"), [], status="no_deviation")

        self.assertEqual(Deviation.objects.get().status, Deviation.Status.DETECTED)

    def test_status_change_is_recorded_in_the_event_log(self) -> None:
        self._sync(self._observation(), [finding()])
        deviation = Deviation.objects.get()

        result = deviations_module.change_status(
            deviation_id=deviation.pk,
            site=self.site,
            status=Deviation.Status.CONFIRMED,
            user_id=None,
            assignee_id=None,
            note="Проверено на площадке",
        )

        self.assertEqual(result["status"], Deviation.Status.CONFIRMED)
        deviation.refresh_from_db()
        self.assertIsNotNone(deviation.confirmed_at)
        event = ProjectEvent.objects.filter(
            kind=ProjectEvent.Kind.DEVIATION_STATUS_CHANGED
        ).first()
        self.assertEqual(event.old_value, "Выявлено")
        self.assertEqual(event.new_value, "Подтверждено")

    def test_closed_deviation_reopens_as_a_new_record(self) -> None:
        """Повторное нарушение после устранения — новое событие, а не воскрешение старого."""
        self._sync(self._observation(), [finding()])
        self._sync(self._observation(status="no_deviation"), [], status="no_deviation")
        self._sync(self._observation(), [finding()])

        self.assertEqual(Deviation.objects.count(), 2)
        self.assertEqual(
            Deviation.objects.filter(status=Deviation.Status.DETECTED).count(), 1
        )
