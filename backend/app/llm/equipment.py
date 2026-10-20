"""Поиск строительной техники на фотографии языковой моделью (ИИ-разметка).

Детектор (YOLO-World) работает на CPU, медленный и на «неудобных» кадрах молчит.
Языковая модель с компьютерным зрением видит кадр целиком и надёжнее отличает
самосвал от грузовика или автокран от крана-манипулятора. Здесь она делает то же,
что и детектор, но выбирает класс СТРОГО из нашего словаря и возвращает рамки.

Честность результата:

* класс вне словаря отбрасывается — модель не может добавить «свою» технику;
* рамки приблизительные (модель оценивает положение, а не измеряет пиксели): модель
  возвращает ``box_2d`` в формате Gemini (0..1000, y первым), мы приводим их к долям
  кадра 0..1 и проверяем на разумность (размер, порядок углов, дубли);
* при любой ошибке возвращается ``available=False`` с причиной, а не выдуманный список.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import client

logger = logging.getLogger(__name__)

#: Меняется вместе с промптом: старые ответы из кэша не должны подхватываться молча.
_PROMPT_VERSION = "equipment-boxes-v3"

_DEFAULT_DETECTION_MODEL = "gemini-2.5-flash"


def detection_model() -> str:
    """Модель для поиска техники с рамками.

    Отдельная от модели оценки стадии: не каждая модель умеет привязывать объекты к пикселям. Claude ставил рамки
    с большими смещениями (квадраты повисали в небе), у Gemini поиск объектов с рамками — штатная функция.
    """
    return os.environ.get("AITUNNEL_DETECTION_MODEL", _DEFAULT_DETECTION_MODEL).strip() or _DEFAULT_DETECTION_MODEL

#: Подсказки различий между похожими классами — именно на них модель чаще всего путается.
_CLASS_HINTS: dict[str, str] = {
    "dump_truck": "грузовик с опрокидывающимся кузовом (самосвал)",
    "truck": "обычный грузовик: бортовой, тентованный, фургон — без опрокидывающегося кузова и без крана",
    "crane_manipulator": "грузовик с откидной складной стрелой-манипулятором на кузове",
    "mobile_crane": "самоходный кран на колёсном или гусеничном шасси, башенный кран",
    "concrete_mixer": "автобетоносмеситель — грузовик с вращающимся барабаном",
    "excavator": "гусеничный или колёсный экскаватор с ковшом на стреле",
    "bulldozer": "бульдозер с отвалом",
    "road_roller": "дорожный каток",
}

_MAX_ITEMS = 20
_MIN_SIDE = 0.01  # рамка уже 1% кадра по любой стороне — шум
_MAX_AREA = 0.92  # рамка на весь кадр — не разметка, а отказ
_NMS_IOU = 0.6

_SYSTEM_PROMPT = (
    "Ты система компьютерного зрения для строительного контроля. По снимку строительной "
    "площадки ты находишь строительную технику ТОЛЬКО из заданного списка классов и для "
    "каждой машины указываешь рамку. Отвечай строго одним JSON-объектом без текста вокруг. "
    "Отмечай только то, что отчётливо видно; не додумывай скрытые, обрезанные почти целиком или "
    "неразличимые вдали объекты. Если техники из списка нет — верни пустой массив. "
    "Людей, легковые автомобили, автобусы, здания и конструкции не отмечай."
)


@dataclass(frozen=True)
class EquipmentBox:
    class_key: str
    label_ru: str
    confidence: float
    #: Углы рамки долями кадра: x1, y1, x2, y2 в диапазоне 0..1, начало координат — верхний левый угол.
    box: tuple[float, float, float, float]


@dataclass(frozen=True)
class EquipmentLocation:
    available: bool
    items: list[EquipmentBox] = field(default_factory=list)
    model: str = ""
    cached: bool = False
    error: str | None = None


def _taxonomy() -> list[dict]:
    """Классы из таксономии ТЗ с подсказками — без отвлекающих классов (машины, люди)."""
    from ..vocabulary import load_vocabulary

    vocabulary = load_vocabulary()
    prompts_by_key: dict[str, list[str]] = {}
    for prompt, info in vocabulary.prompt_to_class.items():
        prompts_by_key.setdefault(info.key, []).append(prompt)

    classes = []
    for info in vocabulary.classes.values():
        if not info.in_taxonomy:
            continue
        classes.append(
            {
                "class_key": info.key,
                "label_ru": info.label_ru,
                "description": _CLASS_HINTS.get(info.key, ""),
                "english_hints": prompts_by_key.get(info.key, [])[:3],
            }
        )
    return classes


def _build_user_prompt(classes: list[dict]) -> str:
    return (
        "Найди на снимке всю строительную технику из списка классов и верни рамки.\n\n"
        f"Список классов: {json.dumps(classes, ensure_ascii=False)}\n\n"
        "Формат ответа — один JSON-объект:\n"
        '{"objects": [{"class_key": "<ключ из списка>", "confidence": <число 0..1>, '
        '"box_2d": [ymin, xmin, ymax, xmax]}]}\n\n'
        "Правила для box_2d: целые координаты, нормализованные к диапазону 0..1000 относительно ВСЕГО "
        "изображения, порядок СНАЧАЛА y, ПОТОМ x: [ymin, xmin, ymax, xmax]; (0, 0) — левый верхний угол. "
        "Рамка плотно охватывает машину целиком вместе со стрелой, ковшом или кузовом. Каждая машина — отдельный объект. "
        "class_key — строго значение из списка. Если сомневаешься в классе — поставь низкую confidence, "
        "а если техника не видна — не добавляй её."
        " Верни не более 20 объектов. Каждую физическую машину укажи строго один раз. "
        "Не повторяй координаты и не дополняй ответ одинаковыми записями. Закончи JSON после последнего уникального объекта."
    )


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _coerce_confidence(raw: object) -> float:
    if isinstance(raw, bool):
        return 0.5
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.5
    if value > 1:  # модель могла ответить в процентах
        value /= 100.0
    return max(0.0, min(1.0, value))


def _coerce_box(raw: object, *, y_first: bool = False) -> tuple[float, float, float, float] | None:
    """Приводит рамку к долям кадра (x1, y1, x2, y2).

    ``y_first`` — формат Gemini ``[ymin, xmin, ymax, xmax]``; иначе ``[x1, y1, x2, y2]``.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        a, b, c, d = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    x1, y1, x2, y2 = (b, a, d, c) if y_first else (a, b, c, d)
    # Координаты 0..1000; если модель ответила долями 0..1 — принимаем и их.
    scale = 1000.0 if max(x1, y1, x2, y2) > 1.5 else 1.0
    x1, y1, x2, y2 = (max(0.0, min(1.0, v / scale)) for v in (x1, y1, x2, y2))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    width, height = x2 - x1, y2 - y1
    if width < _MIN_SIDE or height < _MIN_SIDE or width * height > _MAX_AREA:
        return None
    return (round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4))


def _normalize(parsed: dict, classes: list[dict]) -> list[EquipmentBox]:
    labels = {item["class_key"]: item["label_ru"] for item in classes}
    raw_objects = parsed.get("objects")
    if not isinstance(raw_objects, list):
        return []

    candidates: list[EquipmentBox] = []
    for entry in raw_objects:
        if not isinstance(entry, dict):
            continue
        class_key = str(entry.get("class_key", "")).strip()
        if class_key not in labels:
            # Класс вне словаря — не подгоняем под ближайший.
            logger.info("ИИ-разметка: класс вне словаря отброшен: %r", class_key)
            continue
        # Предпочитаем нативный формат Gemini (box_2d, y первым); простой box [x1, y1, x2, y2] — запасной вариант.
        if "box_2d" in entry:
            box = _coerce_box(entry.get("box_2d"), y_first=True)
        else:
            box = _coerce_box(entry.get("box"))
        if box is None:
            continue
        candidates.append(
            EquipmentBox(
                class_key=class_key,
                label_ru=labels[class_key],
                confidence=_coerce_confidence(entry.get("confidence")),
                box=box,
            )
        )

    # Подавление дублей: два почти одинаковых квадрата одного класса — одна машина.
    candidates.sort(key=lambda item: -item.confidence)
    kept: list[EquipmentBox] = []
    for item in candidates:
        if any(k.class_key == item.class_key and _iou(k.box, item.box) > _NMS_IOU for k in kept):
            continue
        kept.append(item)
    return kept[:_MAX_ITEMS]


def locate_equipment(
    image_path: Path,
    *,
    image_sha256: str | None = None,
    use_cache: bool = True,
    extra_classes: list[dict] | None = None,
) -> EquipmentLocation:
    """Находит на снимке технику из словаря и возвращает рамки долями кадра."""
    if not image_path.is_file():
        return EquipmentLocation(available=False, error=f"файл не найден: {image_path}")

    try:
        classes = _taxonomy()
    except Exception:
        logger.exception("Не удалось загрузить словарь классов для ИИ-разметки")
        return EquipmentLocation(available=False, error="не удалось загрузить словарь классов")
    if not classes:
        return EquipmentLocation(available=False, error="словарь классов пуст")

    if extra_classes:
        known = {item["class_key"] for item in classes}
        classes = classes + [item for item in extra_classes if item["class_key"] not in known]

    digest = image_sha256 or client.file_sha256(image_path)
    class_signature = ",".join(sorted(item["class_key"] for item in classes))
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _build_user_prompt(classes)},
                {"type": "image_url", "image_url": {"url": client.image_data_url(image_path)}},
            ],
        },
    ]
    result = client.chat(
        messages,
        cache_key=f"{_PROMPT_VERSION}|{class_signature}|{digest}",
        model=detection_model(),
        # Pro includes reasoning in the token budget; 3000 can cut off the JSON itself.
        max_tokens=12000 if "gemini" in detection_model() and "pro" in detection_model() else 3000,
        temperature=0.1,
        use_cache=use_cache,
    )
    if not result.available:
        return EquipmentLocation(available=False, error=result.error)

    parsed = client.parse_json_response(result.text)
    if parsed is None:
        logger.warning("ИИ-разметка: неразбираемый ответ для %s", image_path.name)
        return EquipmentLocation(
            available=False,
            error="ответ модели не удалось разобрать как JSON",
            model=result.model,
        )

    return EquipmentLocation(
        available=True,
        items=_normalize(parsed, classes),
        model=result.model,
        cached=result.cached,
    )
