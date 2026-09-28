"""Модуль «AI Learning»: коррекции инженера и версии классификатора-корректора.

Идея (см. план): вместо дообучения всего YOLO-World — лёгкий классификатор
поверх CLIP-эмбеддингов, обучаемый на подтверждениях/исправлениях инженера
по неоднозначным или низкоуверенным детекциям (см. detector.py,
confusable_class_pairs). Коррекции инженера — единственный в проекте реально
размеченный человеком датасет (у исходных 100 снимков нет разметки классов,
см. data/config/splits.json), поэтому именно они одновременно и обучающие
данные, и материал для честной валидации (train/test-разбиение внутри самих
коррекций, см. scripts/train_correction_classifier.py) — отдельного
эталонного held-out набора в проекте не существует.

Как и insights.py, здесь нет файлового отката: при недоступности БД функции
возвращают честный `available: False`/`None`, а не выдуманные данные.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import uuid
from pathlib import Path

from . import config, django_bridge, persistence

logger = logging.getLogger(__name__)

CORRECTIONS_DIR = config.UPLOADS_DIR / "corrections"
TRAIN_SCRIPT_PATH = config.ROOT / "scripts" / "train_correction_classifier.py"


def db_available() -> bool:
    return django_bridge.ensure_django_ready()


def save_correction(
    *,
    observation_id: str,
    bbox: list[float],
    original_class_key: str,
    original_confidence: float | None,
    corrected_class_key: str | None,
    user_id: int,
    site=None,
) -> dict | None:
    """Обрезает фрагмент снимка наблюдения по bbox и сохраняет коррекцию.

    Возвращает None, если БД недоступна, наблюдение не найдено/принадлежит другому
    проекту или файл снимка отсутствует на диске — вызывающий код (main.py) должен
    вернуть честную ошибку клиенту, а не имитировать успех.
    """
    if not db_available():
        return None

    image_path_str = persistence.get_observation_image_path(observation_id, site=site)
    if image_path_str is None:
        return None
    image_path = Path(image_path_str)
    if not image_path.is_file():
        return None

    from django.contrib.auth.models import User
    from PIL import Image

    from core.models import Correction as CorrectionRow
    from core.models import Observation as ObservationRow
    from core.models import VocabularyClass

    try:
        observation_qs = ObservationRow.objects.filter(id=observation_id)
        observation_qs = (
            observation_qs.filter(zone__site=site)
            if site is not None
            else observation_qs.filter(zone__site__is_legacy=True)
        )
        observation = observation_qs.get()
    except ObservationRow.DoesNotExist:
        return None

    if len(bbox) != 4:
        return None

    try:
        with Image.open(image_path) as img:
            width, height = img.size
            x1, y1, x2, y2 = bbox
            clamped_x1 = max(0, min(int(x1), width - 1))
            clamped_y1 = max(0, min(int(y1), height - 1))
            clamped_x2 = max(clamped_x1 + 1, min(int(x2), width))
            clamped_y2 = max(clamped_y1 + 1, min(int(y2), height))
            crop = img.convert("RGB").crop((clamped_x1, clamped_y1, clamped_x2, clamped_y2))

            CORRECTIONS_DIR.mkdir(parents=True, exist_ok=True)
            crop_path = CORRECTIONS_DIR / f"{uuid.uuid4()}.jpg"
            crop.save(crop_path, format="JPEG", quality=90)
    except Exception:
        logger.exception("Не удалось обрезать фрагмент снимка для коррекции")
        return None

    corrected_class = None
    if corrected_class_key:
        corrected_class = VocabularyClass.objects.filter(key=corrected_class_key).first()

    created_by = User.objects.filter(id=user_id).first()

    correction = CorrectionRow.objects.create(
        observation=observation,
        crop_image_path=str(crop_path),
        bbox=[clamped_x1, clamped_y1, clamped_x2, clamped_y2],
        original_class_key=original_class_key,
        original_confidence=original_confidence,
        corrected_class=corrected_class,
        created_by=created_by,
    )

    return {
        "id": correction.id,
        "crop_image_path": correction.crop_image_path,
        "original_class_key": correction.original_class_key,
        "corrected_class_key": corrected_class.key if corrected_class else None,
        "created_at": correction.created_at.isoformat(),
    }


def _version_to_dict(version) -> dict:
    return {
        "id": version.id,
        "version_label": version.version_label,
        "status": version.status,
        "status_label_ru": version.get_status_display(),
        "trained_at": version.trained_at.isoformat() if version.trained_at else None,
        "training_sample_count": version.training_sample_count,
        "metrics": version.metrics_json,
        "created_at": version.created_at.isoformat(),
    }


def learning_stats() -> dict:
    """Реальные счётчики для «Центра обучения AI»: подтверждения/исправления/не-техника.

    Корректор-классификатор — legacy-only функциональность (см. план, граница AI Learning):
    статистика считается только по коррекциям legacy-проекта; орфанные коррекции
    (observation=NULL) и коррекции других проектов исключены.
    """
    if not db_available():
        return {"available": False}

    from core.models import Correction, ModelVersion

    total = confirmations = fixed_errors = negatives = 0
    legacy_corrections = Correction.objects.select_related("corrected_class").filter(
        observation__isnull=False, observation__zone__site__is_legacy=True
    )
    for correction in legacy_corrections:
        total += 1
        if correction.corrected_class is None:
            negatives += 1
        elif correction.corrected_class.key == correction.original_class_key:
            confirmations += 1
        else:
            fixed_errors += 1

    production = ModelVersion.objects.filter(status=ModelVersion.Status.PRODUCTION).first()
    candidates = list(
        ModelVersion.objects.filter(status=ModelVersion.Status.CANDIDATE).order_by("-created_at")
    )

    return {
        "available": True,
        "correction_count": total,
        "confirmation_count": confirmations,
        "fixed_error_count": fixed_errors,
        "not_equipment_count": negatives,
        "production_version": _version_to_dict(production) if production else None,
        "candidate_versions": [_version_to_dict(v) for v in candidates],
    }


def list_model_versions() -> dict:
    if not db_available():
        return {"available": False, "versions": []}
    from core.models import ModelVersion

    versions = ModelVersion.objects.all().order_by("-created_at")
    return {"available": True, "versions": [_version_to_dict(v) for v in versions]}


def count_available_corrections() -> int:
    """Считает только коррекции legacy-проекта — именно они идут в обучение классификатора-корректора."""
    if not db_available():
        return 0
    from core.models import Correction

    return Correction.objects.filter(
        observation__isnull=False, observation__zone__site__is_legacy=True
    ).count()


def trigger_training() -> dict:
    """Запускает обучение классификатора-корректора в фоне (subprocess, без Celery/Redis).

    Сам скрипт (scripts/train_correction_classifier.py) создаёт ModelVersion со
    статусом `candidate` по завершении — здесь только честно фиксируется факт
    запуска, без выдуманного прогресса или мгновенного результата.
    """
    if count_available_corrections() == 0:
        return {"started": False, "reason": "Нет ни одной коррекции — обучать не на чем"}

    try:
        # Фиксированный путь к своему же скрипту, без пользовательского ввода.
        subprocess.Popen(
            [sys.executable, str(TRAIN_SCRIPT_PATH)],
            cwd=str(config.ROOT),
        )
    except Exception:
        logger.exception("Не удалось запустить процесс обучения классификатора-корректора")
        return {"started": False, "reason": "Не удалось запустить процесс обучения"}

    return {"started": True}


def deploy_version(version_id: int) -> dict | None:
    """Переводит кандидата в production, прежнюю production-версию — в архив."""
    if not db_available():
        return None
    from django.db import transaction

    from core.models import ModelVersion

    try:
        candidate = ModelVersion.objects.get(id=version_id)
    except ModelVersion.DoesNotExist:
        return None

    with transaction.atomic():
        ModelVersion.objects.filter(status=ModelVersion.Status.PRODUCTION).update(
            status=ModelVersion.Status.ARCHIVED
        )
        candidate.status = ModelVersion.Status.PRODUCTION
        candidate.save(update_fields=["status"])

    return _version_to_dict(candidate)
