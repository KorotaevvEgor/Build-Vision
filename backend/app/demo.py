"""Публичный демонстрационный разбор снимка — без авторизации и без базы.

Экран для жюри и для первого знакомства: перетащил фотографию, увидел
рамки с классами, стадию, готовность и комментарий модели. Никакого
проекта, графика и истории здесь нет, и это принципиально: выводы о
сроках без графика были бы выдумкой, поэтому их тут нет вообще.

Эндпоинт открыт наружу, поэтому он обязан быть скучным и защищённым:

* результат никуда не сохраняется, файл удаляется сразу после разбора;
* размер файла ограничен, чтение потоковое — заявленный Content-Length
  не имеет значения, считается фактически прочитанное;
* простое ограничение частоты по адресу: детекция и обращение к языковой
  модели стоят дорого, и открытая форма без счётчика — это приглашение
  положить демонстрацию ровно в момент показа.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
from collections import deque
from dataclasses import asdict
from pathlib import Path
from threading import Lock

from . import config

logger = logging.getLogger(__name__)

#: Подготовленная выборка для показа: собирается scripts/prepare_demo_gallery.py.
DEMO_MANIFEST_PATH = config.CONFIG_DIR / "demo_gallery.json"

#: Ограничения демонстрационного эндпоинта. Значения заданы с запасом под
#: реальные кадры камер (около 2 МБ) и под темп показа на защите.
MAX_IMAGE_BYTES = 12 * 1024 * 1024
RATE_LIMIT_REQUESTS = int(os.environ.get("SK_DEMO_RATE_LIMIT", "15"))
RATE_LIMIT_WINDOW_SECONDS = 600

_ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

_requests_by_client: dict[str, deque[float]] = {}
_rate_lock = Lock()


class TooLarge(Exception):
    """Файл превысил допустимый размер."""


class RateLimited(Exception):
    """Превышена частота обращений с одного адреса."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Слишком много запросов")
        self.retry_after_seconds = retry_after_seconds


def check_rate_limit(client_key: str) -> None:
    """Скользящее окно по адресу. Память чистится тем же проходом."""
    now = time.monotonic()
    with _rate_lock:
        history = _requests_by_client.setdefault(client_key, deque())
        while history and now - history[0] > RATE_LIMIT_WINDOW_SECONDS:
            history.popleft()
        if len(history) >= RATE_LIMIT_REQUESTS:
            retry_after = int(RATE_LIMIT_WINDOW_SECONDS - (now - history[0])) + 1
            raise RateLimited(retry_after)
        history.append(now)
        if not history:
            _requests_by_client.pop(client_key, None)


def _load_manifest() -> list[dict]:
    """Читает перечень примеров с диска.

    Намеренно без кэша в памяти: файл маленький, а во время подготовки к показу
    выборка пересобирается часто, и перезапускать сервер ради этого не должно быть нужно.
    """
    if not DEMO_MANIFEST_PATH.is_file():
        return []
    try:
        data = json.loads(DEMO_MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Не удалось прочитать перечень демонстрационных примеров")
        return []
    return data.get("samples") or []


def list_samples() -> dict:
    samples = [
        {
            "id": item["id"],
            "title": item.get("title", item["id"]),
            "scenario": item.get("scenario", ""),
            "season": item.get("season", ""),
            "stage_label": item.get("stage_label", ""),
            "readiness_percent": item.get("readiness_percent"),
            "date_stamp": item.get("date_stamp"),
            "warmed": bool(item.get("warmed")),
        }
        for item in _load_manifest()
        if sample_image_path(item["id"]) is not None
    ]
    return {"available": bool(samples), "samples": samples}


def sample_image_path(sample_id: str) -> Path | None:
    """Путь к файлу примера с проверкой, что он действительно из каталога данных.

    Идентификатор приходит из адреса без авторизации, поэтому путь собирается
    только из манифеста и проверяется на выход за пределы каталога данных.
    """
    for item in _load_manifest():
        if item["id"] != sample_id:
            continue
        candidate = (config.ROOT / item["path"]).resolve()
        if candidate.is_file() and candidate.is_relative_to(config.DATA_DIR.resolve()):
            return candidate
        return None
    return None


def safe_suffix(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in _ALLOWED_SUFFIXES else ".jpg"


def save_temp_image(file_obj, suffix: str) -> tuple[Path, str]:
    """Сохраняет загруженный файл во временный каталог и считает его хэш.

    Размер контролируется по факту чтения, а не по заголовку: заголовку
    клиента доверять нельзя, а поток можно оборвать на первом лишнем байте.
    """
    temp_dir = Path(tempfile.gettempdir()) / "buildvision-demo"
    temp_dir.mkdir(parents=True, exist_ok=True)
    path = temp_dir / f"{uuid.uuid4()}{suffix}"

    hasher = hashlib.sha256()
    written = 0
    try:
        with path.open("wb") as out:
            while chunk := file_obj.read(512 * 1024):
                written += len(chunk)
                if written > MAX_IMAGE_BYTES:
                    raise TooLarge
                hasher.update(chunk)
                out.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    if written == 0:
        path.unlink(missing_ok=True)
        raise ValueError("Пустой файл")
    return path, hasher.hexdigest()


def analyze(image_path: Path, image_sha256: str) -> dict:
    """Разбирает снимок: детекция, стадия по фото, короткий комментарий.

    Ни одна часть не обязательна: если языковая модель недоступна, рамки
    всё равно вернутся, а отсутствие оценки будет показано честно.
    """
    from .detector import get_detector
    from .llm import assess_photo, build_photo_comment, llm_is_configured
    from .rules_config import load_equipment_rules

    detector = get_detector()
    # Классификатор-корректор обучен на коррекциях конкретного проекта —
    # на публичном экране со случайной фотографией его применять неверно.
    detections = detector.detect(image_path, apply_correction_classifier=False)

    counts: dict[str, dict] = {}
    for item in detections:
        if not item.in_taxonomy or item.ambiguous:
            continue
        entry = counts.setdefault(
            item.class_key,
            {"class_key": item.class_key, "label_ru": item.label_ru, "count": 0, "max_confidence": 0.0},
        )
        entry["count"] += 1
        entry["max_confidence"] = max(entry["max_confidence"], item.confidence)

    vision = None
    comment = {"available": False, "text": "", "error": "языковая модель не настроена"}
    if llm_is_configured():
        try:
            assessment = assess_photo(image_path, image_sha256=image_sha256)
            vision = asdict(assessment)
        except Exception:
            logger.exception("Демонстрационная оценка снимка не выполнена")
            vision = None

        if vision and vision.get("available"):
            payload = {
                "stage": vision["stage_label"],
                "readiness_percent": vision["readiness_percent"],
                "visual_evidence": vision["visual_evidence"],
                "confidence": vision["confidence"],
                "detected_equipment": {
                    entry["label_ru"]: entry["count"] for entry in counts.values()
                },
            }
            try:
                result = build_photo_comment(payload)
                comment = {
                    "available": result.available,
                    "text": result.text,
                    "model": result.model,
                    "cached": result.cached,
                    "error": result.error,
                }
            except Exception:
                logger.exception("Демонстрационный комментарий не сформирован")
                comment = {"available": False, "text": "", "error": "внутренняя ошибка"}

    # По каким из найденных классов у нас есть измеренные проблемы качества.
    # Показать посетителю «Самосвал × 25», зная из собственного замера, что точность
    # этого класса низкая, и не сказать об этом — введение в заблуждение.
    detected_classes = {entry["class_key"] for entry in counts.values()}
    try:
        rules = load_equipment_rules()
        limitations = [
            {
                "class_key": item.class_key,
                "label_ru": item.label_ru,
                "issue": item.issue,
                "description": item.description,
            }
            for item in rules.known_limitations
            if item.class_key in detected_classes
        ]
    except Exception:
        logger.exception("Не удалось загрузить известные ограничения для демонстрации")
        limitations = []

    return {
        "detections": [
            {
                "class_key": d.class_key,
                "label_ru": d.label_ru,
                "in_taxonomy": d.in_taxonomy,
                "confidence": d.confidence,
                "bbox": d.bbox,
                "ambiguous": d.ambiguous,
                "runner_up_class_key": d.runner_up_class_key,
            }
            for d in detections
        ],
        "equipment_counts": sorted(counts.values(), key=lambda e: -e["max_confidence"]),
        "known_limitations": limitations,
        "vision": vision,
        "comment": comment,
        "image_sha256": image_sha256,
        "note": (
            "Это разбор одиночной фотографии без календарного графика: система показывает, "
            "что видит, но не судит о сроках. Сопоставление с планом работ, определение "
            "простоя и отклонений доступны внутри проекта."
        ),
    }
