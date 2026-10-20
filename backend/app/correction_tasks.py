"""Project-scoped review tasks. Drafts never overwrite detector observations."""
from __future__ import annotations

import math
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from . import auth, learning
from .project_scope import get_project_site

router = APIRouter(prefix="/api/projects/{project_id}/correction-tasks")

class TaskCreate(BaseModel):
    observation_id: uuid.UUID

class TaskUpdate(BaseModel):
    revision: int = Field(ge=1)
    status: str | None = None
    annotations: list[dict] | None = Field(default=None, max_length=300)
    empty_scene: bool | None = None
    before_id: int | None = Field(default=None, ge=1)

class TrainingRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=100)

def _vocabulary():
    from core.models import VocabularyClass
    return list(VocabularyClass.objects.filter(in_taxonomy=True).order_by("label_ru").values("key", "label_ru"))

def _dimensions(observation):
    if observation.image_width and observation.image_height:
        return observation.image_width, observation.image_height
    try:
        from PIL import Image
        with Image.open(observation.image_path) as image:
            return image.size
    except (OSError, ValueError):
        return 0, 0

def _editable(task, user):
    return task.status != "training" and (user.role == "admin" or task.assignee_id in (None, user.id))

def serialize_task(task, user):
    from .correction_training import serialize_run
    width, height = _dimensions(task.observation)
    return {"id": task.pk, "observation_id": str(task.observation_id), "title": task.title,
            "reason": task.reason, "status": task.status, "assignee_id": task.assignee_id,
            "assignee": (task.assignee.get_full_name() or task.assignee.username) if task.assignee else None,
            "annotations": task.annotations, "empty_scene": task.empty_scene, "revision": task.revision,
            "created_at": task.created_at.isoformat(), "updated_at": task.updated_at.isoformat(),
            "training_run": serialize_run(task.training_run) if task.training_run else None,
            "image_width": width, "image_height": height, "editable": _editable(task, user), "history": task.history}

def _tasks(site):
    from core.models import CorrectionTask
    return CorrectionTask.objects.filter(site=site).select_related("observation", "assignee", "training_run__model_version")

def _get(task_id, site, lock=False):
    qs = _tasks(site)
    if lock:
        # PostgreSQL cannot lock nullable relations from select_related outer joins.
        qs = qs.select_for_update(of=("self",))
    task = qs.filter(pk=task_id).first()
    if task is None:
        raise HTTPException(404, "Задание не найдено в этом проекте")
    return task

def _log(task, user, action, old_status):
    from django.utils import timezone
    task.history = [*task.history, {"at": timezone.now().isoformat(), "actor": user.username,
                                  "action": action, "from": old_status, "to": task.status}][-200:]

def _create(observation, site):
    from core.models import CorrectionTask
    if observation.detections.count() > 300:
        raise HTTPException(422, "На снимке более 300 объектов. Выберите кадр с меньшей областью обзора для проверки")
    width, height = _dimensions(observation)
    annotations = []
    for detection in observation.detections.all()[:300]:
        box = detection.bbox
        if not isinstance(box, list) or len(box) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in box):
            continue
        if width and height:
            box = [max(0, min(width-1, box[0])), max(0, min(height-1, box[1])),
                   max(1, min(width, box[2])), max(1, min(height, box[3]))]
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        annotations.append({"id": str(detection.pk), "bbox": box, "original_class_key": detection.class_key,
                            "original_confidence": detection.confidence, "corrected_class_key": ""})
    camera = observation.camera.name if observation.camera else observation.zone.name
    return CorrectionTask.objects.get_or_create(site=site, observation=observation, defaults={
        "title": f"Проверить распознавание · {camera}"[:255], "reason": "Неоднозначное или требующее проверки распознавание. Подтвердите классы и границы объектов.",
        "annotations": annotations, "position": -time.time_ns() // 1000})

def enqueue_if_needed(observation_id, site):
    """Queue only real persisted uncertain detections; do not block the main analysis."""
    import logging
    from django.db.models import Q
    from core.models import Observation
    try:
        observation = Observation.objects.filter(pk=observation_id, zone__site=site).select_related("camera", "zone").first()
        if observation and observation.detections.filter(Q(ambiguous=True) | Q(confidence__lt=.65)).exists():
            return _create(observation, site)[1]
    except Exception:
        logging.getLogger(__name__).exception("Не удалось добавить наблюдение в очередь коррекций")
    return False

@router.get("")
def list_tasks(site=Depends(get_project_site), current_user=Depends(auth.get_current_user)):
    from core.models import CorrectionTask, Observation
    from .correction_training import recover_stale_runs
    recover_stale_runs(site)
    rows = list(_tasks(site))
    sources = [{"observation_id": str(o.pk), "label": f"{o.camera.name if o.camera else o.zone.name} · {o.observed_date or 'Дата не подтверждена'}",
                "date_confirmed": o.date_confirmed, "observed_date": str(o.observed_date) if o.observed_date else None}
               for o in Observation.objects.filter(zone__site=site).select_related("camera", "zone").order_by("-created_at")[:100]]
    return {"items": [serialize_task(t, current_user) for t in rows], "counts": {s: sum(t.status == s for t in rows) for s, _ in CorrectionTask.Status.choices},
            "statuses": [{"key": k, "label": v} for k, v in CorrectionTask.Status.choices], "vocabulary": _vocabulary(), "sources": sources, "can_train": current_user.role == "admin"}

@router.post("/sync")
def sync_tasks(site=Depends(get_project_site), current_user=Depends(auth.get_current_user)):
    from core.models import Observation
    from django.db.models import Q
    from django.db.models import Count
    candidates = Observation.objects.filter(zone__site=site).exclude(correction_tasks__site=site).annotate(object_count=Count("detections", distinct=True)).filter(object_count__lte=300).filter(Q(detections__ambiguous=True) | Q(detections__confidence__lt=.65)).distinct().select_related("camera", "zone").prefetch_related("detections").order_by("-created_at")[:500]
    created = sum(_create(o, site)[1] for o in candidates)
    return {"created": created}

@router.post("")
def create_task(payload: TaskCreate, site=Depends(get_project_site), current_user=Depends(auth.get_current_user)):
    from core.models import Observation
    observation = Observation.objects.filter(pk=payload.observation_id, zone__site=site).select_related("camera", "zone").prefetch_related("detections").first()
    if not observation:
        raise HTTPException(404, "Снимок не найден в этом проекте")
    task, _ = _create(observation, site)
    return {"task": serialize_task(task, current_user)}

@router.post("/train")
def train_tasks(payload: TrainingRequest, site=Depends(get_project_site), current_user=Depends(auth.get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(403, "Запуск обучения доступен администратору")
    from .correction_training import start_training
    return {"run": start_training(site, current_user.id, payload.task_ids)}

@router.get("/{task_id}")
def task_detail(task_id: int, site=Depends(get_project_site), current_user=Depends(auth.get_current_user)):
    return {"task": serialize_task(_get(task_id, site), current_user), "vocabulary": _vocabulary(), "can_train": current_user.role == "admin"}

def _validate_annotations(task, annotations, empty_scene, ready):
    width, height = _dimensions(task.observation)
    if not width or not height:
        raise HTTPException(422, "Исходный снимок недоступен. Разметку нельзя проверить")
    keys = {v["key"] for v in _vocabulary()}
    previous = {a["id"]: a for a in task.annotations}
    seen, result = set(), []
    for annotation in annotations:
        ident, box = annotation.get("id"), annotation.get("bbox")
        if not isinstance(ident, str) or not ident or len(ident) > 64 or ident in seen:
            raise HTTPException(422, "У каждой рамки должен быть уникальный идентификатор")
        seen.add(ident)
        if not isinstance(box, list) or len(box) != 4 or not all(type(x) in (int, float) and math.isfinite(x) for x in box):
            raise HTTPException(422, "Рамка должна содержать четыре конечных координаты")
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height and x2-x1 >= 1 and y2-y1 >= 1):
            raise HTTPException(422, "Рамка должна быть внутри изображения и не меньше одного пикселя")
        label = annotation.get("corrected_class_key", "")
        if label is not None and not isinstance(label, str):
            raise HTTPException(422, "Класс должен быть строкой или значением «Не техника»")
        if label is not None and label != "" and label not in keys:
            raise HTTPException(422, "Выбран неизвестный класс техники")
        if ready and label == "":
            raise HTTPException(422, "Подтвердите класс каждой рамки или выберите «Не техника»")
        original = previous.get(ident, {})
        result.append({"id": ident, "bbox": box, "corrected_class_key": label,
                       "original_class_key": original.get("original_class_key", ""),
                       "original_confidence": original.get("original_confidence")})
    if ready and not result and not empty_scene:
        raise HTTPException(422, "Добавьте разметку или подтвердите, что на кадре нет объектов для обучения")
    if empty_scene and result:
        raise HTTPException(422, "Пустой кадр не должен содержать рамок")
    return result

@router.patch("/{task_id}")
def update_task(task_id: int, payload: TaskUpdate, site=Depends(get_project_site), current_user=Depends(auth.get_current_user)):
    from core.models import ConstructionSite, CorrectionTask
    from django.db import transaction
    new_crops = []
    try:
        with transaction.atomic():
            ConstructionSite.objects.select_for_update().get(pk=site.pk)
            task = _get(task_id, site, lock=True)
            if task.revision != payload.revision:
                raise HTTPException(409, "Задание изменилось. Обновите его перед сохранением")
            if not _editable(task, current_user):
                raise HTTPException(403, "Задание занято другим исполнителем или находится на обучении")
            old_status, target = task.status, payload.status or task.status
            transitions = {"todo": {"in_progress"}, "in_progress": {"todo", "ready"}, "ready": {"todo", "in_progress"}, "trained": {"in_progress"}, "training": set()}
            if target != old_status and target not in transitions[old_status]:
                raise HTTPException(422, "Недопустимый переход. Обучение и его результат управляются отдельным запуском")
            task.status = target
            editing = payload.annotations is not None or payload.empty_scene is not None
            if editing and old_status != "in_progress":
                raise HTTPException(422, "Сначала возьмите задание в работу")
            if editing or (target == "ready" and old_status != target):
                task.empty_scene = payload.empty_scene if payload.empty_scene is not None else task.empty_scene
                task.annotations = _validate_annotations(task, payload.annotations if payload.annotations is not None else task.annotations, task.empty_scene, target == "ready")
            if target == "in_progress" and old_status != target:
                task.assignee_id = current_user.id
                task.training_run = None
            if target == "todo":
                task.assignee = None
            if target == "ready" and old_status != target:
                correction_ids = []
                for a in task.annotations:
                    result = learning.save_correction(observation_id=str(task.observation_id), bbox=a["bbox"], original_class_key=a["original_class_key"], original_confidence=a["original_confidence"], corrected_class_key=a["corrected_class_key"], user_id=current_user.id, site=site)
                    if result is None:
                        raise HTTPException(422, "Не удалось сохранить обучающий фрагмент. Проверьте доступность исходного снимка")
                    new_crops.append(result["crop_image_path"])
                    correction_ids.append(result["id"])
                task.corrections.set(correction_ids)
                task.training_run = None
            if "before_id" in payload.model_fields_set:
                peers = list(CorrectionTask.objects.filter(site=site, status=target).exclude(pk=task.pk).order_by("position", "-created_at", "-id"))
                if payload.before_id is not None and payload.before_id not in {p.pk for p in peers}:
                    raise HTTPException(422, "Позиция назначения отсутствует в этой колонке")
                index = next((i for i, p in enumerate(peers) if p.pk == payload.before_id), len(peers))
                peers.insert(index, task)
                for index, peer in enumerate(peers):
                    peer.position = index * 1024
                CorrectionTask.objects.bulk_update([p for p in peers if p.pk != task.pk], ["position"])
            elif old_status != target:
                task.position = -time.time_ns() // 1000
            task.revision += 1
            _log(task, current_user, "Разметка сохранена" if editing else "Задание перемещено", old_status)
            task.save()
    except Exception:
        # Only remove files created by this failed request; historical crops stay intact.
        for crop in new_crops:
            path = Path(crop)
            if path.resolve().is_relative_to(learning.CORRECTIONS_DIR.resolve()):
                path.unlink(missing_ok=True)
        raise
    return {"task": serialize_task(_get(task_id, site), current_user)}
