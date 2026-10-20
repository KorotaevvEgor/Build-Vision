"""Обёртка над YOLO-World: загружается один раз, переиспользуется между запросами.

Модель загружается лениво при первом вызове и держится в памяти процесса —
именно так задумано размещение на VPS (см. план: «один серверный worker,
одна копия модели»). Здесь же применяется эвристика неоднозначности между
классами, которые baseline показал как систематически перепутываемые
(экскаватор/кран-манипулятор): если два лучших класса одной рамки по
уверенности ближе ambiguity_margin — рамка помечается ambiguous=True,
а не выдаётся как надёжный класс.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import config, django_bridge, runtime_settings
from .rules_config import load_equipment_rules
from .vocabulary import Vocabulary, load_vocabulary

logger = logging.getLogger(__name__)

# Определение человека отключено по требованию заказчика: путать людей с техникой
# опаснее, чем их пропускать, а сама по себе фиксация людей на площадке не входит
# в задачу контроля техники. Класс остаётся в словаре/промптах ниже — это помогает
# модели отличать человека от техники по-прежнему, просто рамки для него
# отбрасываются перед тем, как результат уйдёт наружу (в БД, на фронтенд).
PERSON_CLASS_KEY = "person"

class DetectorBusyError(RuntimeError):
    """Bounded inference admission, so concurrent uploads cannot queue indefinitely."""


@dataclass
class Detection:
    class_key: str
    label_ru: str
    in_taxonomy: bool
    confidence: float
    bbox: list[float]
    ambiguous: bool
    runner_up_class_key: str | None
    runner_up_confidence: float | None

    # Заполняется после детекции, когда известна камера и её зоны (см. activity.py).
    # Сам детектор про зоны не знает и знать не должен: его дело — найти технику.
    frame_zone_id: int | None = None
    frame_zone_name: str = ""
    frame_zone_kind: str = ""
    activity: str = "unknown"
    activity_reason: str = ""


class Detector:
    """Синглтон-обёртка. Не создавайте несколько экземпляров на процесс —
    каждый держит собственную копию весов и текстового энкодера в памяти."""

    _lock = threading.Lock()

    def __init__(
        self,
        weights: str = config.DEFAULT_MODEL_WEIGHTS,
        imgsz: int = config.DEFAULT_IMGSZ,
        conf: float = config.DEFAULT_CONF,
        iou: float = config.DEFAULT_IOU,
        max_det: int = config.DEFAULT_MAX_DET,
        class_thresholds: dict[str, float] | None = None,
    ) -> None:
        self.weights = weights
        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        self.max_det = max_det
        self._model = None
        # Сериализует сам вызов predict(): после появления фонового переанализа
        # (см. reanalysis.py) детекция может вызываться одновременно из фонового потока и из
        # обычного запроса загрузки фото; без гарантий потокобезопасности
        # Ultralytics/YOLO-World при конкурентном инференсе на CPU безопаснее просто всегда
        # выполнять predict() по одному.
        self._predict_lock = threading.Lock()
        self._request_slots = threading.BoundedSemaphore(2)
        self.vocabulary: Vocabulary = load_vocabulary()
        # Explicit opt-in only: calibration must be validated on independent
        # annotated scenes before deployment. This gate can only raise the
        # runtime global threshold, never recover boxes removed by YOLO/NMS.
        if class_thresholds is None:
            class_thresholds = json.loads(os.environ.get("SK_DETECTOR_CLASS_THRESHOLDS_JSON", "{}"))
        if not isinstance(class_thresholds, dict):
            raise TypeError("Class thresholds must be a JSON object")
        self.class_thresholds = {}
        for key, value in class_thresholds.items():
            if key not in self.vocabulary.classes or isinstance(value, bool):
                raise ValueError(f"Invalid detector class threshold: {key}")
            try:
                threshold = float(value)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid detector class threshold: {key}") from exc
            if not math.isfinite(threshold) or not 0 <= threshold <= 1:
                raise ValueError(f"Invalid detector class threshold: {key}")
            self.class_thresholds[key] = threshold
        rules = load_equipment_rules()
        # Неориентированные пары классов, которые baseline показал как путаемые.
        self._confusable_pairs = {frozenset(pair) for pair in rules.confusable_class_pairs}
        self._ambiguity_margin = rules.ambiguity_margin
        # Кэш активного production-классификатора-корректора (см. модуль «Learning»):
        # (id версии, загруженный артефакт) — перезагружается, только если id изменился.
        self._correction_classifier_cache: tuple[int, dict] | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from ultralytics import YOLOWorld

            weights_path = config.MODELS_DIR / self.weights
            config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
            model = YOLOWorld(str(weights_path))
            model.set_classes(self.vocabulary.prompts)
            self._model = model

    def _is_confusable(self, a: str, b: str) -> bool:
        return frozenset((a, b)) in self._confusable_pairs

    def detect(self, image_path: Path, *, apply_correction_classifier: bool = True, site_id: int | None = None, execution_trace: dict | None = None) -> list[Detection]:
        if not self._request_slots.acquire(blocking=False):
            raise DetectorBusyError('Детектор занят обработкой снимков. Повторите загрузку через несколько секунд.')
        try:
            return self._detect(image_path, apply_correction_classifier=apply_correction_classifier, site_id=site_id, execution_trace=execution_trace)
        finally:
            self._request_slots.release()

    def _detect(self, image_path: Path, *, apply_correction_classifier: bool = True, site_id: int | None = None, execution_trace: dict | None = None) -> list[Detection]:
        trace = execution_trace if execution_trace is not None else {}
        trace["run_id"] = str(uuid.uuid4())
        trace.update(detector={"status": "running", "weights": self.weights}, correction={"status": "unused", "reason": "disabled", "site_id": site_id})
        self._ensure_loaded()
        # Порог берётся из настроек на каждый вызов: инженер меняет его в
        # интерфейсе и сразу видит результат на следующем снимке, без перезапуска.
        settings = runtime_settings.load()
        with self._predict_lock:
            result = self._model.predict(
                source=str(image_path),
                imgsz=self.imgsz,
                conf=settings.detector_confidence,
                iou=self.iou,
                max_det=self.max_det,
                agnostic_nms=True,
                device="cpu",
                verbose=False,
            )[0]

        names = result.names
        # Важно: baseline показал, что экскаватор путается с краном-манипулятором
        # С ВЫСОКОЙ уверенностью (0.78–0.96) — порог по confidence эти случаи не
        # отфильтрует. Поэтому для известных confusable-пар прототип
        # честно помечает результат как всегда неоднозначный (независимо от
        # confidence) и показывает оба возможных класса инженеру для ручного
        # подтверждения, вместо того чтобы выдавать ложно уверенный ответ.
        # ambiguity_margin здесь не используется как порог confidence именно поэтому.
        detections: list[Detection] = []
        for box in result.boxes:
            prompt = names[int(box.cls.item())]
            info = self.vocabulary.class_for_prompt(prompt)
            if info.key == PERSON_CLASS_KEY:
                continue
            confidence = float(box.conf.item())
            if confidence < max(settings.detector_confidence, self.class_thresholds.get(info.key, 0)):
                continue
            ambiguous = False
            runner_up_key = None
            runner_up_conf = None

            if info.in_taxonomy:
                partners = self._confusable_partners(info.key)
                if partners:
                    ambiguous = True
                    runner_up_key = partners[0]
                    runner_up_conf = None

            detections.append(
                Detection(
                    class_key=info.key,
                    label_ru=info.label_ru,
                    in_taxonomy=info.in_taxonomy,
                    confidence=round(confidence, 4),
                    bbox=[round(float(v), 1) for v in box.xyxy[0].tolist()],
                    ambiguous=ambiguous,
                    runner_up_class_key=runner_up_key,
                    runner_up_confidence=runner_up_conf,
                )
            )

        detections.sort(key=lambda d: -d.confidence)
        # Only an explicitly published production version in this exact scope may run.
        if apply_correction_classifier:
            self._apply_correction_classifier(image_path, detections, site_id=site_id, execution_trace=trace["correction"])
        trace["detector"].update(status="participated", detection_count=len(detections), confidence=settings.detector_confidence)
        return detections

    def _load_correction_classifier(self, *, site_id: int | None = None, execution_trace: dict | None = None) -> dict | None:
        """См. модуль «Learning»: если есть обученный и опубликованный
        production-классификатор-корректор, возвращает его; иначе None — тогда
        поведение не меняется (честная логика confusable-пар сохраняется как есть).
        """
        trace = execution_trace if execution_trace is not None else {}
        if not django_bridge.ensure_django_ready():
            trace.update(status="unused", reason="database_unavailable")
            return None
        try:
            from core.models import ModelVersion

            production = (
                ModelVersion.objects.filter(status=ModelVersion.Status.PRODUCTION, site_id=site_id)
                .exclude(artifact_path="")
                .order_by("-created_at")
                .first()
            )
        except Exception:
            trace.update(status="error", reason="version_lookup_failed")
            logger.exception("Не удалось проверить production-версию классификатора-корректора")
            return None

        if production is None:
            trace.update(status="unused", reason="no_production_version")
            self._correction_classifier_cache = None
            return None
        trace["version_id"] = production.id
        cached = self._correction_classifier_cache
        if cached is not None and cached[0] == production.id:
            return cached[1]

        try:
            import joblib

            artifact = joblib.load(production.artifact_path)
        except Exception:
            trace.update(status="error", reason="artifact_load_failed")
            logger.exception("Не удалось загрузить артефакт классификатора-корректора")
            return None

        self._correction_classifier_cache = (production.id, artifact)
        return artifact

    def _apply_correction_classifier(self, image_path: Path, detections: list[Detection], *, site_id: int | None = None, execution_trace: dict | None = None) -> None:
        """Уточняет неоднозначные детекции обученным на коррекциях классификатором.

        Не подменяет ambiguous=True на False — решение классификатора показывается
        инженеру как уточнение, а не выдаётся за окончательно надёжный результат.
        """
        trace = execution_trace if execution_trace is not None else {}
        ambiguous_detections = [d for d in detections if d.ambiguous]
        trace.update(candidate_count=len(ambiguous_detections), classified_count=0, changed_count=0)
        if not ambiguous_detections:
            trace.update(status="unused", reason="no_ambiguous_detections")
            return
        artifact = self._load_correction_classifier(site_id=site_id, execution_trace=trace)
        if artifact is None:
            return

        try:
            from PIL import Image

            from . import clip_embeddings

            with Image.open(image_path) as img:
                rgb_image = img.convert("RGB")
                for detection in ambiguous_detections:
                    x1, y1, x2, y2 = detection.bbox
                    crop = rgb_image.crop(
                        (max(0, int(x1)), max(0, int(y1)), max(1, int(x2)), max(1, int(y2)))
                    )
                    if crop.width < 2 or crop.height < 2:
                        continue
                    embedding = clip_embeddings.embed_image_from_pil(crop)
                    predicted_key = artifact["model"].predict([embedding])[0]
                    trace["classified_count"] += 1
                    if predicted_key == config.CORRECTION_NOT_EQUIPMENT_LABEL:
                        continue
                    info = self.vocabulary.classes.get(predicted_key)
                    if info is None or info.key == detection.class_key:
                        continue
                    trace["changed_count"] += 1
                    detection.runner_up_class_key = detection.class_key
                    detection.class_key = info.key
                    detection.label_ru = info.label_ru
                    detection.in_taxonomy = info.in_taxonomy
            trace.update(status="participated" if trace["classified_count"] else "unused", reason="classified" if trace["classified_count"] else "no_valid_crops")
        except Exception:
            trace.update(status="error", reason="classification_failed")
            logger.exception("Классификатор-корректор недоступен, используется исходная детекция")

    def _confusable_partners(self, class_key: str) -> list[str]:
        partners = []
        for pair in self._confusable_pairs:
            if class_key in pair:
                partners.extend(k for k in pair if k != class_key)
        return partners


_detector_singleton: Detector | None = None
_singleton_lock = threading.Lock()


def get_detector() -> Detector:
    global _detector_singleton
    if _detector_singleton is None:
        with _singleton_lock:
            if _detector_singleton is None:
                _detector_singleton = Detector()
    return _detector_singleton
