import sys
from pathlib import Path
from unittest.mock import patch
import tempfile
from datetime import timedelta

from django.test import SimpleTestCase
from django.test import TransactionTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))


class GroupValidationTests(SimpleTestCase):
    def test_single_observation_cannot_supply_validation(self):
        from app.correction_training import train_classifier
        classifier, metrics = train_classifier([[1, 0], [0, 1]], ["a", "b"], ["frame", "frame"])
        self.assertFalse(metrics["available"])
        self.assertEqual(set(classifier.classes_), {"a", "b"})

    def test_grouped_validation_never_splits_observation(self):
        from app.correction_training import train_classifier
        x = [[1, 0], [0, 1]] * 6
        _, metrics = train_classifier(x, ["a", "b"] * 6, [str(i // 2) for i in range(12)])
        self.assertTrue(metrics["available"])
        self.assertEqual(metrics["split_unit"], "observation")


class TrainingRunTests(TransactionTestCase):
    def setUp(self):
        from core.models import ConstructionSite, Zone, Observation, VocabularyClass, Correction, CorrectionTask
        from django.contrib.auth.models import User
        self.user = User.objects.create_user("training-admin")
        self.site = ConstructionSite.objects.create(name="Training test")
        zone = Zone.objects.create(site=self.site, external_id="train-zone", name="Zone", geometry_geojson={})
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        crop = Path(self.temp.name) / "crop.jpg"
        crop.write_bytes(b"mock-crop")
        self.tasks = []
        for i in range(2):
            obs = Observation.objects.create(zone=zone, image_path=str(crop), image_sha256=str(i),
                overall_status="no_deviation", overall_explanation="test")
            label = VocabularyClass.objects.create(key=f"train-{i}", label_ru=f"Class {i}")
            correction = Correction.objects.create(observation=obs, crop_image_path=str(crop), corrected_class=label)
            task = CorrectionTask.objects.create(site=self.site, observation=obs, title="Task", status="ready")
            task.corrections.add(correction)
            self.tasks.append(task)

    def start(self):
        from app.correction_training import start_training
        with patch("app.correction_training.subprocess.Popen"):
            return start_training(self.site, self.user.pk, [t.pk for t in self.tasks])

    def test_success_is_scoped_candidate_with_real_artifact(self):
        from app.correction_training import run_training
        from core.models import CorrectionTrainingRun
        run = self.start()
        with patch("app.clip_embeddings.embed_image", side_effect=[[1., 0.], [0., 1.]]), patch("app.correction_training.config.MODELS_DIR", Path(self.temp.name)):
            run_training(run["id"])
        row = CorrectionTrainingRun.objects.get(pk=run["id"])
        self.assertEqual(row.status, "succeeded")
        self.assertIsNone(row.active_slot)
        self.assertEqual(row.model_version.site_id, self.site.pk)
        self.assertEqual(row.model_version.status, "candidate")
        self.assertTrue(Path(row.model_version.artifact_path).is_file())
        for task in self.tasks:
            task.refresh_from_db()
            self.assertEqual(task.status, "trained")
            self.assertEqual(task.revision, 3)
            self.assertEqual(len(task.history), 2)

    def test_embedding_failure_releases_slot_and_returns_ready(self):
        from app.correction_training import run_training
        from core.models import CorrectionTrainingRun
        run = self.start()
        with patch("app.clip_embeddings.embed_image", side_effect=RuntimeError("embedding unavailable")):
            run_training(run["id"])
        row = CorrectionTrainingRun.objects.get(pk=run["id"])
        self.assertEqual(row.status, "failed")
        self.assertIn("embedding unavailable", row.error)
        self.assertIsNone(row.active_slot)
        self.tasks[0].refresh_from_db()
        self.assertEqual(self.tasks[0].status, "ready")

    def test_duplicate_training_conflicts(self):
        from app.correction_training import start_training
        from fastapi import HTTPException
        self.start()
        with self.assertRaises(HTTPException) as caught:
            start_training(self.site, self.user.pk, [t.pk for t in self.tasks])
        self.assertEqual(caught.exception.status_code, 409)

    def test_stale_worker_is_failed(self):
        from app.correction_training import recover_stale_runs
        from core.models import CorrectionTrainingRun
        from django.utils import timezone
        run = self.start()
        CorrectionTrainingRun.objects.filter(pk=run["id"]).update(created_at=timezone.now() - timedelta(hours=3))
        recover_stale_runs(self.site)
        self.assertEqual(CorrectionTrainingRun.objects.get(pk=run["id"]).status, "failed")

    def test_foreign_project_task_rejected(self):
        from app.correction_training import start_training
        from core.models import ConstructionSite
        from fastapi import HTTPException
        other = ConstructionSite.objects.create(name="Foreign")
        with self.assertRaises(HTTPException) as caught:
            start_training(other, self.user.pk, [self.tasks[0].pk])
        self.assertEqual(caught.exception.status_code, 422)

    def test_launch_failure_retains_failed_audit_and_ready_tasks(self):
        from app.correction_training import start_training
        with patch("app.correction_training.subprocess.Popen", side_effect=OSError("worker unavailable")):
            run = start_training(self.site, self.user.pk, [t.pk for t in self.tasks])
        self.assertEqual(run["status"], "failed")
        self.assertIn("worker unavailable", run["error"])
        self.tasks[0].refresh_from_db()
        self.assertEqual(self.tasks[0].status, "ready")

    def test_one_class_is_actionable_validation_error(self):
        from app.correction_training import start_training
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            start_training(self.site, self.user.pk, [self.tasks[0].pk])
        self.assertEqual(caught.exception.status_code, 422)
        self.tasks[0].refresh_from_db()
        self.assertEqual(self.tasks[0].status, "ready")

    def test_repeat_uploads_share_validation_group(self):
        from app.correction_training import run_training, train_classifier
        from core.models import Observation
        Observation.objects.filter(pk__in=[t.observation_id for t in self.tasks]).update(image_sha256="same-source-sha")
        run = self.start()
        with patch("app.clip_embeddings.embed_image", side_effect=[[1., 0.], [0., 1.]]), patch("app.correction_training.config.MODELS_DIR", Path(self.temp.name)), patch("app.correction_training.train_classifier", wraps=train_classifier) as train:
            run_training(run["id"])
        self.assertEqual(train.call_args.args[2], ["same-source-sha", "same-source-sha"])
