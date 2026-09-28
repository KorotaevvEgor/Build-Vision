"""Обёртка над CLIP-визуальным энкодером для классификатора-корректора.

YOLO-World (см. detector.py) уже тянет пакет `clip` как зависимость для
текстового энкодера промптов (`set_classes`) — тот же пакет используется
здесь для получения векторного представления обрезка изображения
(224x224, ViT-B/32 — базовая конфигурация CLIP, которую по умолчанию
использует и сама ultralytics для YOLO-World). Отдельная от YOLO-World
загрузка модели — осознанное упрощение: у ultralytics нет публичного
API для извлечения визуальных эмбеддингов из уже загруженной модели
детекции, а тянуть новую зависимость ради этого не нужно, раз `clip`
уже есть в requirements.txt.

Модель грузится лениво и один раз на процесс (тот же паттерн, что и в
detector.py) — используется и в backend (main.py, при инференсе), и в
отдельном процессе scripts/train_correction_classifier.py.
"""

from __future__ import annotations

import threading
from pathlib import Path

_lock = threading.Lock()
_model = None
_preprocess = None
_device = "cpu"


def _ensure_loaded() -> None:
    global _model, _preprocess
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        import clip

        model, preprocess = clip.load("ViT-B/32", device=_device)
        model.eval()
        _model = model
        _preprocess = preprocess


def embed_image(image_path: Path) -> list[float]:
    """Возвращает L2-нормированный CLIP-эмбеддинг изображения с диска (512 чисел для ViT-B/32)."""
    from PIL import Image

    with Image.open(image_path) as img:
        return embed_image_from_pil(img.convert("RGB"))


def embed_image_from_pil(image) -> list[float]:
    """То же самое, но для уже загруженного в память фрагмента (без промежуточного файла на диске)."""
    _ensure_loaded()
    import torch

    tensor = _preprocess(image).unsqueeze(0).to(_device)
    with torch.no_grad():
        features = _model.encode_image(tensor)
        features = features / features.norm(dim=-1, keepdim=True)

    return features.squeeze(0).cpu().tolist()
