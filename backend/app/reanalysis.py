"""Повторный анализ уже сохранённых наблюдений.

Нужен, когда меняется порог уверенности детектора (чувствительность): старые
снимки должны получить актуальные рамки, а не оставаться с результатами по
старому порогу до следующей случайной загрузки фото по той же камере.
Переиспользует те же функции, что и обычный конвейер анализа снимка (см.
`_run_observation_pipeline` в projects_router.py) — только без сохранения нового
файла и без пересчёта отклонений/AI-обогащения, которые к порогу детектора
не относятся.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import django_bridge, observation_ai
from .app_context import get_context
from .detector import get_detector
from .matching import evaluate_observation

logger = logging.getLogger(__name__)


def reanalyze_all_observations() -> dict:
    """Пересчитывает детекции и оценку этапов для всех сохранённых наблюдений.

    Проходит по всем проектам (включая legacy), поэтому корректно подхватывает
    per-project графики/правила через `app_context.get_context(site=...)`.
    Ошибка на одном наблюдении или проекте не должна останавливать остальные —
    это фоновая задача, и частичный результат лучше, чем никакого.
    """
    if not django_bridge.ensure_django_ready():
        logger.warning("Переанализ пропущен: база данных недоступна")
        return {"total": 0, "updated": 0, "errors": 0}

    from core.models import ConstructionSite, Observation
    from . import persistence as persistence_module

    detector = get_detector()
    total = 0
    updated = 0
    errors = 0

    for site in ConstructionSite.objects.all():
        try:
            ctx = get_context(site=site)
        except Exception:
            logger.exception("Не удалось загрузить контекст проекта %s для переанализа", site.pk)
            continue

        observations = (
            Observation.objects.filter(zone__site=site)
            .select_related("zone", "camera")
            .order_by("created_at")
        )
        for observation in observations:
            total += 1
            image_path = Path(observation.image_path)
            if not image_path.is_file():
                continue
            try:
                detections = detector.detect(image_path, apply_correction_classifier=site.is_legacy)
                camera_external_id = observation.camera.external_id if observation.camera_id else None
                image_size = (
                    (observation.image_width, observation.image_height)
                    if observation.image_width and observation.image_height
                    else None
                )
                observation_ai.apply_zones_and_activity(
                    detections,
                    camera_external_id=camera_external_id,
                    image_size=image_size,
                    observed_date=observation.observed_date if observation.date_confirmed else None,
                )
                evaluation = evaluate_observation(
                    zone_id=observation.zone.external_id,
                    observed_date=observation.observed_date,
                    date_confirmed=observation.date_confirmed,
                    detections=detections,
                    schedule=ctx.schedule,
                    rules=ctx.rules,
                )
                persistence_module.replace_observation_results(observation, evaluation)
                updated += 1
            except Exception:
                errors += 1
                logger.exception("Не удалось переанализировать наблюдение %s", observation.id)

    logger.info(
        "Переанализ по новому порогу уверенности завершён: всего %s, обновлено %s, ошибок %s",
        total,
        updated,
        errors,
    )
    return {"total": total, "updated": updated, "errors": errors}
