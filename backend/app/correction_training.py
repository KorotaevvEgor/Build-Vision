"""Project-scoped correction training, with a durable global worker lock."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import subprocess
import sys
import uuid

from fastapi import HTTPException
from . import config

TRAIN_SCRIPT_PATH = config.ROOT / "scripts" / "train_correction_tasks.py"


def _move_tasks(queryset, status, run):
    from django.utils import timezone
    for task in queryset.select_for_update():
        task.history = list(task.history or []) + [{"at": timezone.now().isoformat(),
            "from": task.status, "to": status, "training_run_id": run.pk}]
        task.status = status
        task.training_run = run
        task.revision += 1
        task.save(update_fields=["history", "status", "training_run", "revision", "updated_at"])


def serialize_run(run):
    version = run.model_version
    from .correction_activation import activation_problem
    problem = activation_problem(version, completed=run.status == "succeeded") if version and version.status == "candidate" else None
    return {"id": run.id, "status": run.status, "error": run.error,
            "model_version_id": run.model_version_id,
            "model_status": version.status if version else None,
            "can_activate": bool(version and version.status == "candidate" and not problem and run.status == "succeeded"),
            "activation_problem": problem,
            "version_label": version.version_label if version else None,
            "metrics": version.metrics_json if version else {},
            **{key: getattr(run, key).isoformat() if getattr(run, key) else None
               for key in ("created_at", "started_at", "finished_at")}}


def _fail(run_id, error):
    from django.db import transaction
    from django.utils import timezone
    from core.models import CorrectionTask, CorrectionTrainingRun
    with transaction.atomic():
        run = CorrectionTrainingRun.objects.select_for_update().get(pk=run_id)
        if run.status not in ("queued", "running"):
            return
        _move_tasks(CorrectionTask.objects.filter(training_run=run, status="training"), "ready", run)
        run.status, run.error, run.active_slot = "failed", str(error)[:4000], None
        run.finished_at = timezone.now()
        run.save()


def recover_stale_runs(site):
    from django.utils import timezone
    from core.models import CorrectionTrainingRun
    # Global recovery also frees an abandoned lock owned by another project.
    cutoff = timezone.now() - timedelta(hours=2)
    stale = CorrectionTrainingRun.objects.filter(status__in=["queued", "running"], created_at__lt=cutoff)
    for run_id in stale.values_list("id", flat=True):
        _fail(run_id, "Процесс обучения не завершился за 2 часа; запустите обучение повторно.")


def _crop_path(raw):
    path = Path(raw)
    return path if path.is_absolute() else config.ROOT / path


def start_training(site, user_id, task_ids):
    from django.db import IntegrityError, transaction
    from core.models import CorrectionTask, CorrectionTrainingRun
    if not task_ids or any(type(i) is not int or i <= 0 for i in task_ids) or len(set(task_ids)) != len(task_ids):
        raise HTTPException(422, "Выберите неповторяющиеся задачи для обучения.")
    recover_stale_runs(site)
    try:
        with transaction.atomic():
            tasks = list(CorrectionTask.objects.select_for_update().filter(site=site, id__in=task_ids))
            if len(tasks) != len(task_ids):
                raise HTTPException(422, "Некоторые задачи не принадлежат проекту.")
            if any(t.status != "ready" for t in tasks):
                raise HTTPException(409, "Обучать можно только готовые задачи.")
            corrections = {}
            for task in tasks:
                rows = list(task.corrections.select_related("corrected_class", "observation__zone"))
                if not rows:
                    raise HTTPException(422, "В каждой задаче должен быть хотя бы один размеченный фрагмент.")
                for row in rows:
                    if not row.observation_id or row.observation.zone.site_id != site.pk or not _crop_path(row.crop_image_path).is_file():
                        raise HTTPException(422, "Размеченный фрагмент отсутствует или принадлежит другому проекту.")
                    corrections[row.pk] = row
            labels = {r.corrected_class.key if r.corrected_class_id else config.CORRECTION_NOT_EQUIPMENT_LABEL for r in corrections.values()}
            if len(labels) < 2:
                raise HTTPException(422, "Для обучения нужны примеры минимум двух разных классов. Выберите также готовое задание с другим классом; «Не техника» — один из возможных вариантов.")
            run = CorrectionTrainingRun.objects.create(site=site, created_by_id=user_id, status="queued", active_slot=1,
                                                       task_ids=sorted(task_ids), correction_ids=sorted(corrections))
            _move_tasks(CorrectionTask.objects.filter(pk__in=task_ids, site=site), "training", run)
    except IntegrityError as exc:
        raise HTTPException(409, "Другой запуск обучения уже выполняется.") from exc
    try:
        subprocess.Popen([sys.executable, str(TRAIN_SCRIPT_PATH), str(run.pk)], cwd=str(config.ROOT),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:
        _fail(run.pk, f"Не удалось запустить процесс обучения: {exc}")
    run.refresh_from_db()
    return serialize_run(run)


def train_classifier(embeddings, labels, groups):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.metrics import accuracy_score
    x, y = np.asarray(embeddings), np.asarray(labels)
    if len(set(labels)) < 2:
        raise ValueError("Для обучения нужны как минимум два класса.")
    metrics = {"available": False, "split_unit": "observation",
               "reason": "Недостаточно независимых наблюдений для проверки всех классов."}
    if len(set(groups)) >= 3:
        for train, test in GroupShuffleSplit(n_splits=20, test_size=.25, random_state=42).split(x, y, groups):
            if set(y[train]) != set(labels) or set(y[test]) != set(labels):
                continue
            evaluator = LogisticRegression(max_iter=1000).fit(x[train], y[train])
            metrics = {"available": True, "split_unit": "observation", "train_count": len(train),
                       "test_count": len(test), "accuracy": float(accuracy_score(y[test], evaluator.predict(x[test]))),
                       "note": "Отложены целые исходные наблюдения; внешнего эталонного набора нет."}
            break
    return LogisticRegression(max_iter=1000).fit(x, y), metrics


def run_training(run_id):
    from django.db import transaction
    from django.utils import timezone
    from core.models import Correction, CorrectionTask, CorrectionTrainingRun, ModelVersion
    from . import clip_embeddings
    artifact = None
    try:
        with transaction.atomic():
            run = CorrectionTrainingRun.objects.select_for_update().get(pk=run_id)
            if run.status != "queued" or run.active_slot != 1:
                return
            run.status, run.started_at = "running", timezone.now()
            run.save()
        rows = list(Correction.objects.select_related("corrected_class", "observation").filter(
            pk__in=run.correction_ids, observation__zone__site_id=run.site_id).order_by("id"))
        if len(rows) != len(run.correction_ids) or not rows:
            raise ValueError("Сохранённая выборка коррекций недоступна.")
        embeddings, labels, groups = [], [], []
        for row in rows:
            crop = _crop_path(row.crop_image_path)
            if not crop.is_file():
                raise ValueError("Файл размеченного фрагмента недоступен.")
            embeddings.append(clip_embeddings.embed_image(crop))
            labels.append(row.corrected_class.key if row.corrected_class_id else config.CORRECTION_NOT_EQUIPMENT_LABEL)
            # Repeated uploads of the same source image must stay in one split.
            groups.append(row.observation.image_sha256 or str(row.observation_id))
        classifier, metrics = train_classifier(embeddings, labels, groups)
        import joblib
        config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        artifact = config.MODELS_DIR / f"correction_project_{run.site_id}_{uuid.uuid4().hex}.joblib"
        joblib.dump({"model": classifier, "classes": sorted(set(labels))}, artifact)
        if not artifact.is_file() or artifact.stat().st_size == 0:
            raise ValueError("Артефакт обученной модели не создан.")
        with transaction.atomic():
            run = CorrectionTrainingRun.objects.select_for_update().get(pk=run_id)
            if run.status != "running" or run.active_slot != 1:
                raise ValueError("Запуск уже остановлен; результат не применяется.")
            version = ModelVersion.objects.create(site_id=run.site_id, version_label=f"board-{run.pk}",
                status="candidate", artifact_path=str(artifact), trained_at=timezone.now(),
                training_sample_count=len(rows), metrics_json=metrics)
            _move_tasks(CorrectionTask.objects.filter(site_id=run.site_id, pk__in=run.task_ids,
                training_run=run, status="training"), "trained", run)
            run.status, run.model_version, run.active_slot = "succeeded", version, None
            run.finished_at = timezone.now()
            run.save()
    except Exception as exc:
        if artifact and artifact.is_file():
            try:
                artifact.unlink()
            except OSError:
                pass
        _fail(run_id, exc)
