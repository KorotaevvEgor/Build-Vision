"""Сохранение результатов анализа в PostgreSQL (история наблюдений).

Пишет Observation + Detection + StageEvaluationRecord через Django ORM —
те же таблицы, что видны и редактируемы в Django admin. Если БД временно
недоступна, ошибка логируется и подавляется: сохранение истории не должно
ломать основной сценарий анализа снимка (см. план — детекция и правила
должны продолжать работать без сети/БД).
"""

from __future__ import annotations

import logging
import uuid

from . import django_bridge
from .detector import Detection
from .matching import ObservationEvaluation, StageEvaluation

logger = logging.getLogger(__name__)


def _detection_dict(detection: Detection) -> dict:
    return {
        "class_key": detection.class_key,
        "label_ru": detection.label_ru,
        "confidence": detection.confidence,
        "ambiguous": detection.ambiguous,
    }


def persist_observation(
    *,
    observation_id: uuid.UUID,
    zone_id: str,
    image_path: str,
    image_sha256: str,
    evaluation: ObservationEvaluation,
    site=None,
    camera_external_id: str | None = None,
    image_size: tuple[int, int] | None = None,
    vision: dict | None = None,
) -> bool:
    """Сохраняет наблюдение и связанные записи. Возвращает True при успехе.

    При явно заданном `site` зона должна принадлежать именно этому проекту —
    иначе (чужая зона) запись отклоняется, чтобы исключить запись в чужой проект.
    """
    if not django_bridge.ensure_django_ready():
        return False

    try:
        from django.db import transaction

        from core.models import Camera as CameraRow
        from core.models import Detection as DetectionRow
        from core.models import Observation as ObservationRow
        from core.models import Stage as StageRow
        from core.models import StageEvaluationRecord
        from core.models import Zone as ZoneRow

        with transaction.atomic():
            zone_qs = ZoneRow.objects.filter(external_id=zone_id)
            zone_qs = zone_qs.filter(site=site) if site is not None else zone_qs.filter(site__is_legacy=True)
            zone = zone_qs.get()

            # Камера должна принадлежать той же зоне: чужая камера сделала бы
            # сравнение с историей кадров бессмысленным.
            camera = None
            if camera_external_id:
                camera = CameraRow.objects.filter(external_id=camera_external_id, zone=zone).first()

            # Оценка по фото сохраняется вместе с наблюдением: иначе кривая готовности
            # объекта потребовала бы повторного обращения к модели по всей истории.
            vision = vision or {}
            observation = ObservationRow.objects.create(
                id=observation_id,
                zone=zone,
                camera=camera,
                image_width=image_size[0] if image_size else None,
                image_height=image_size[1] if image_size else None,
                image_path=image_path,
                image_sha256=image_sha256,
                observed_date=evaluation.observed_date,
                date_confirmed=evaluation.date_confirmed,
                overall_status=evaluation.overall_status,
                overall_explanation=evaluation.overall_explanation_ru,
                vision_stage_key=vision.get("stage_key", "") if vision.get("available") else "",
                vision_stage_label=vision.get("stage_label", "") if vision.get("available") else "",
                readiness_percent=vision.get("readiness_percent") if vision.get("available") else None,
            )

            DetectionRow.objects.bulk_create(
                DetectionRow(
                    observation=observation,
                    class_key=d.class_key,
                    label_ru=d.label_ru,
                    in_taxonomy=d.in_taxonomy,
                    confidence=d.confidence,
                    bbox=d.bbox,
                    ambiguous=d.ambiguous,
                    runner_up_class_key=d.runner_up_class_key or "",
                    frame_zone_id=getattr(d, "frame_zone_id", None),
                    activity=getattr(d, "activity", "unknown"),
                    activity_reason=getattr(d, "activity_reason", "")[:300],
                )
                for d in evaluation.all_detections
            )

            for stage_eval in evaluation.stage_evaluations:
                _create_stage_evaluation_row(StageEvaluationRecord, StageRow, observation, stage_eval)

        return True
    except Exception:
        logger.exception("Не удалось сохранить результат анализа в БД")
        return False


def replace_observation_results(observation, evaluation: ObservationEvaluation) -> None:
    """Перезаписывает результаты уже сохранённого наблюдения новым прогоном анализа.

    Нужен при переанализе после изменения порога уверенности детектора (см.
    reanalysis.py) — в отличие от persist_observation, не создаёт новую запись наблюдения,
    а заменяет детекции и оценки по этапам у уже существующей.
    """
    from core.models import Detection as DetectionRow
    from core.models import Stage as StageRow
    from core.models import StageEvaluationRecord

    observation.overall_status = evaluation.overall_status
    observation.overall_explanation = evaluation.overall_explanation_ru
    observation.save(update_fields=["overall_status", "overall_explanation"])

    DetectionRow.objects.filter(observation=observation).delete()
    DetectionRow.objects.bulk_create(
        DetectionRow(
            observation=observation,
            class_key=d.class_key,
            label_ru=d.label_ru,
            in_taxonomy=d.in_taxonomy,
            confidence=d.confidence,
            bbox=d.bbox,
            ambiguous=d.ambiguous,
            runner_up_class_key=d.runner_up_class_key or "",
            frame_zone_id=getattr(d, "frame_zone_id", None),
            activity=getattr(d, "activity", "unknown"),
            activity_reason=getattr(d, "activity_reason", "")[:300],
        )
        for d in evaluation.all_detections
    )

    StageEvaluationRecord.objects.filter(observation=observation).delete()
    for stage_eval in evaluation.stage_evaluations:
        _create_stage_evaluation_row(StageEvaluationRecord, StageRow, observation, stage_eval)


def _quantity_check_dict(check) -> dict:
    return {
        "class_key": check.class_key,
        "label_ru": check.label_ru,
        "required_qty": check.required_qty,
        "actual_qty": check.actual_qty,
        "satisfied": check.satisfied,
    }


def _create_stage_evaluation_row(model, stage_model, observation, stage_eval: StageEvaluation) -> None:
    stage_row = stage_model.objects.filter(external_id=stage_eval.stage_id).first()
    model.objects.create(
        observation=observation,
        stage=stage_row,
        work_name_snapshot=stage_eval.work_name,
        status=stage_eval.status,
        explanation=stage_eval.explanation_ru,
        required_snapshot=stage_eval.required,
        allowed_snapshot=stage_eval.allowed,
        quantity_checks_snapshot=[_quantity_check_dict(c) for c in stage_eval.quantity_checks],
        missing_required=stage_eval.missing_required,
        unexpected_detections=[_detection_dict(d) for d in stage_eval.unexpected_detections],
        ambiguous_detections=[_detection_dict(d) for d in stage_eval.ambiguous_detections],
    )


def update_observation_vision(observation_id: uuid.UUID, vision: dict | None) -> None:
    """Дописывает оценку по фото после обогащения языковой моделью.

    Оценка появляется позже сохранения наблюдения, и менять порядок ради неё
    нельзя: анализ снимка обязан сохраниться даже если модель недоступна.
    Поэтому оценка дописывается отдельным шагом и тихо пропускается при ошибке.
    """
    if not vision or not vision.get("available") or not django_bridge.ensure_django_ready():
        return
    try:
        from core.models import Observation as ObservationRow

        ObservationRow.objects.filter(id=observation_id).update(
            vision_stage_key=vision.get("stage_key", ""),
            vision_stage_label=vision.get("stage_label", ""),
            readiness_percent=vision.get("readiness_percent"),
        )
    except Exception:
        logger.exception("Не удалось сохранить оценку по фото")


def get_observation_image_path(observation_id: str, site=None) -> str | None:
    """Возвращает путь к файлу снимка наблюдения для отдачи через API (см. main.py)."""
    if not django_bridge.ensure_django_ready():
        return None
    try:
        from core.models import Observation as ObservationRow

        qs = ObservationRow.objects.filter(id=observation_id)
        qs = qs.filter(zone__site=site) if site is not None else qs.filter(zone__site__is_legacy=True)
        observation = qs.only("image_path").first()
        return observation.image_path if observation else None
    except Exception:
        logger.exception("Не удалось прочитать путь к снимку наблюдения из БД")
        return None


def get_observation(observation_id: str, site=None) -> dict | None:
    """Читает сохранённое наблюдение по id. None — если БД недоступна, не найдено или принадлежит другому проекту."""
    if not django_bridge.ensure_django_ready():
        return None

    try:
        from core.models import Observation as ObservationRow

        qs = (
            ObservationRow.objects.select_related("zone")
            .prefetch_related("detections", "stage_evaluations", "stage_evaluations__stage")
            .filter(id=observation_id)
        )
        qs = qs.filter(zone__site=site) if site is not None else qs.filter(zone__site__is_legacy=True)
        observation = qs.first()
        if observation is None:
            return None

        return {
            "observation_id": str(observation.id),
            "zone_id": observation.zone.external_id,
            "image_sha256": observation.image_sha256,
            "observed_date": observation.observed_date.isoformat() if observation.observed_date else None,
            "date_confirmed": observation.date_confirmed,
            "overall_status": observation.overall_status,
            "overall_status_label_ru": observation.get_overall_status_display(),
            "overall_explanation_ru": observation.overall_explanation,
            "created_at": observation.created_at.isoformat(),
            "detections": [
                {
                    "class_key": d.class_key,
                    "label_ru": d.label_ru,
                    "in_taxonomy": d.in_taxonomy,
                    "confidence": d.confidence,
                    "bbox": d.bbox,
                    "ambiguous": d.ambiguous,
                    "runner_up_class_key": d.runner_up_class_key or None,
                }
                for d in observation.detections.all()
            ],
            "stages": [
                {
                    "stage_id": e.stage.external_id if e.stage else None,
                    "work_name": e.work_name_snapshot,
                    "status": e.status,
                    "status_label_ru": e.get_status_display(),
                    "required": e.required_snapshot,
                    "allowed": e.allowed_snapshot,
                    "quantity_checks": e.quantity_checks_snapshot,
                    "missing_required": e.missing_required,
                    "explanation_ru": e.explanation,
                    "unexpected_detections": e.unexpected_detections,
                    "ambiguous_detections": e.ambiguous_detections,
                }
                for e in observation.stage_evaluations.all()
            ],
        }
    except Exception:
        logger.exception("Не удалось прочитать наблюдение из БД")
        return None
