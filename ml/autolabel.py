"""Полуавтоматическая разметка выданных снимков: рамки от детектора, классы от VLM.

Зачем так. Выданные заказчиком 100 снимков не размечены, а размечать плотные
панорамы вручную — это день работы. При этом измеренная проблема текущего
детектора не в поиске объектов, а в их классификации: на снимке котлована он
находит примерно столько рамок, сколько там техники, но называет экскаваторы
автокранами, а трубы — самосвалами.

Отсюда разделение труда. Рамки предлагает детектор с низким порогом
уверенности (нужна полнота, а не точность). Класс каждой рамки определяет
мультимодальная модель по вырезанному фрагменту: на отдельном кропе, где объект
занимает весь кадр, она отвечает существенно надёжнее, чем на общей панораме.
Результат — черновая разметка, которую инженер проверяет глазами, а не рисует
с нуля.

Чтобы не делать тысячи запросов, кропы собираются в сетку с номерами: один
запрос классифицирует до девяти фрагментов сразу.

Запуск:
    .venv-ml\\Scripts\\python.exe ml\\autolabel.py --limit 5        # пробный прогон
    .venv-ml\\Scripts\\python.exe ml\\autolabel.py                  # все снимки
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests
import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import env_loader  # noqa: F401  (загружает ключи доступа из .env)

TAXONOMY_PATH = ROOT / "ml" / "taxonomy.yaml"
VOCABULARY_PATH = ROOT / "data" / "config" / "vocabulary.yaml"
IMAGES_DIR = ROOT / "data" / "raw" / "images"
OUTPUT_DIR = ROOT / "data" / "datasets" / "autolabeled"
REVIEW_DIR = ROOT / "data" / "runs" / "autolabel-review"

# Порог намеренно низкий: на этом шаге важна полнота рамок, а не их чистота.
# Ошибочные предложения отсеет классификатор-VLM, пометив их как «не техника».
PROPOSAL_CONF = 0.12
PROPOSAL_IOU = 0.55
MAX_PROPOSALS_PER_IMAGE = 40

CROP_PADDING = 0.06
CROP_SIZE = 320
GRID_COLUMNS = 3
GRID_ROWS = 3
BATCH_SIZE = GRID_COLUMNS * GRID_ROWS

NOT_EQUIPMENT = "not_equipment"

# Отвлекающие варианты ответа. Без них модели некуда деть провод или легковую
# машину: когда единственная альтернатива — общий отказ, она склоняется к
# правдоподобному классу и называет кабель рукавом бетононасоса. Явно названные
# варианты дают ей куда отнести такой фрагмент. Все они сводятся к отказу.
DISTRACTOR_OPTIONS = {
    "passenger_car": "Легковой автомобиль, микроавтобус или фургон доставки",
    "cable_or_hose": "Провод, трос, кабель или шланг",
    "pipe_or_material": "Труба, плита, штабель материалов, контейнер, бытовка",
    "structure": "Здание, забор, опалубка, леса, шпунтовое ограждение",
    "ground_or_background": "Грунт, небо, деревья, вода или просто фон",
    "person": "Человек",
    NOT_EQUIPMENT: "Непонятно или фрагмент слишком мелкий/размытый",
}

# Фрагменты меньше этого размера не отправляются на классификацию: на двадцати
# пикселях невозможно отличить экскаватор от погрузчика, и любой ответ будет угадыванием.
MIN_BOX_SIDE_PX = 28

# Доля площади меньшей рамки внутри большей, при которой меньшая считается дублём.
# На высокой технике (буровые установки, краны) разные промпты дают вложенные
# рамки — на мачту, на шасси и на машину целиком. IoU их не ловит, потому что
# площади сильно разные, а вложенность — ловит.
CONTAINMENT_THRESHOLD = 0.6
IOU_MERGE_THRESHOLD = 0.35

# После классификации две рамки одного класса с заметным пересечением почти всегда
# один и тот же объект, даже если до классификации они прошли как разные кандидаты.
SAME_CLASS_IOU_THRESHOLD = 0.15
SAME_CLASS_CONTAINMENT_THRESHOLD = 0.4


@dataclass
class Proposal:
    bbox: tuple[float, float, float, float]
    source_class: str
    confidence: float
    assigned_key: str | None = None
    assigned_confidence: str = "low"


CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def accepts_confidence(reported: str, minimum: str) -> bool:
    """Проходит ли уверенность модели заданный порог строгости."""
    return CONFIDENCE_ORDER.get(reported, -1) >= CONFIDENCE_ORDER.get(minimum, 2)


def read_min_confidence_from_settings() -> str:
    """Берёт строгость из настроек приложения, чтобы она совпадала с интерфейсом.

    Оффлайн-скрипт не должен жить по своим правилам: если инженер выбрал в
    настройках строгий режим, разметка тоже должна быть строгой.
    При недоступной базе возвращается самый осторожный вариант.
    """
    try:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin_panel.settings")
        import django

        django.setup()
        from core.models import MatchingSettings

        row = MatchingSettings.objects.first()
        if row is not None:
            return row.autolabel_min_vlm_confidence
    except Exception:
        print("настройки из базы недоступны, используется строгий режим")
    return "high"


def load_taxonomy() -> tuple[list[str], dict[str, str]]:
    data = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))
    keys = [item["key"] for item in data["classes"]]
    labels = {item["key"]: item["label_ru"] for item in data["classes"]}
    return keys, labels


def load_proposal_prompts() -> list[str]:
    """Собирает промпты для генерации рамок из словаря проекта.

    Детальные промпты вроде «crawler excavator with digging bucket arm» дают
    существенно больше кандидатов, чем обобщённое «construction machine»:
    на пробном прогоне разница была в десять раз. Класс промпта значения не
    имеет: на этом шаге нужны только координаты, классифицирует VLM по кропу.
    """
    data = yaml.safe_load(VOCABULARY_PATH.read_text(encoding="utf-8"))
    prompts: list[str] = []
    for group in ("classes", "distractors"):
        for item in data.get(group, []) or []:
            prompts.extend(item.get("prompts", []))
    # Дополняем типами, которых в старом словаре нет, но которые есть в кадрах.
    prompts.extend(
        [
            "tower crane",
            "pile driving rig",
            "drilling rig with tall mast",
            "wheel loader",
            "concrete pump truck",
        ]
    )
    return prompts


def build_proposals(image_path: Path, model) -> list[Proposal]:
    """Предлагает рамки текущим детектором с низким порогом уверенности."""
    result = model.predict(
        source=str(image_path),
        imgsz=960,
        conf=PROPOSAL_CONF,
        iou=PROPOSAL_IOU,
        max_det=MAX_PROPOSALS_PER_IMAGE,
        agnostic_nms=True,
        verbose=False,
    )[0]
    proposals = []
    for box in result.boxes:
        x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
        proposals.append(
            Proposal(
                bbox=(x1, y1, x2, y2),
                source_class=result.names[int(box.cls.item())],
                confidence=float(box.conf.item()),
            )
        )
    return proposals


def _intersection_area(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top)


def _area(box: tuple[float, ...]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _center_inside(inner: tuple[float, ...], outer: tuple[float, ...]) -> bool:
    center_x = (inner[0] + inner[2]) / 2
    center_y = (inner[1] + inner[3]) / 2
    return outer[0] <= center_x <= outer[2] and outer[1] <= center_y <= outer[3]


def deduplicate(proposals: list[Proposal]) -> list[Proposal]:
    """Убирает дублирующие и вложенные рамки, оставляя самую уверенную.

    Штатный NMS внутри детектора здесь не справляется: мы сознательно
    задаём десятки промптов ради полноты, и одна буровая установка получает
    пять рамок разного размера. Без дедупликации они все уйдут в разметку
    и научат модель предсказывать по пять объектов там, где один.
    """
    ordered = sorted(proposals, key=lambda p: -p.confidence)
    kept: list[Proposal] = []
    for candidate in ordered:
        candidate_area = _area(candidate.bbox)
        if candidate_area <= 0:
            continue
        duplicate = False
        for existing in kept:
            intersection = _intersection_area(candidate.bbox, existing.bbox)
            if intersection <= 0:
                continue
            union = candidate_area + _area(existing.bbox) - intersection
            iou = intersection / union if union > 0 else 0.0
            containment = intersection / min(candidate_area, _area(existing.bbox))
            if iou >= IOU_MERGE_THRESHOLD or containment >= CONTAINMENT_THRESHOLD:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
    return kept


def _caption_font() -> ImageFont.ImageFont:
    """Шрифт с кириллицей: встроенный шрифт PIL рисует её квадратиками."""
    for candidate in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"):
        try:
            return ImageFont.truetype(candidate, 15)
        except OSError:
            continue
    return ImageFont.load_default()


def crop_with_padding(image: Image.Image, bbox: tuple[float, float, float, float]) -> Image.Image:
    """Вырезает фрагмент с полями: контекст вокруг машины помогает узнать её тип."""
    x1, y1, x2, y2 = bbox
    pad_x = (x2 - x1) * CROP_PADDING
    pad_y = (y2 - y1) * CROP_PADDING
    box = (
        max(0, int(x1 - pad_x)),
        max(0, int(y1 - pad_y)),
        min(image.width, int(x2 + pad_x)),
        min(image.height, int(y2 + pad_y)),
    )
    crop = image.crop(box)
    crop.thumbnail((CROP_SIZE, CROP_SIZE))
    return crop


def build_grid(crops: list[Image.Image]) -> Image.Image:
    """Собирает кропы в пронумерованную сетку — один запрос вместо девяти."""
    cell = CROP_SIZE
    grid = Image.new("RGB", (cell * GRID_COLUMNS, cell * GRID_ROWS), (24, 24, 28))
    draw = ImageDraw.Draw(grid)
    for index, crop in enumerate(crops):
        column, row = index % GRID_COLUMNS, index // GRID_COLUMNS
        offset_x = column * cell + (cell - crop.width) // 2
        offset_y = row * cell + (cell - crop.height) // 2
        grid.paste(crop, (offset_x, offset_y))
        draw.rectangle(
            [column * cell, row * cell, (column + 1) * cell - 1, (row + 1) * cell - 1],
            outline=(90, 90, 100),
        )
        label = str(index + 1)
        draw.rectangle([column * cell + 2, row * cell + 2, column * cell + 26, row * cell + 24], fill=(0, 0, 0))
        draw.text((column * cell + 9, row * cell + 7), label, fill=(255, 255, 255))
    return grid


def classify_grid(grid: Image.Image, count: int, labels: dict[str, str]) -> dict[int, tuple[str, str]]:
    """Классифицирует фрагменты сетки. Возвращает номер → (класс, уверенность)."""
    options = dict(labels)
    options.update(DISTRACTOR_OPTIONS)
    prompt = (
        f"На изображении сетка из пронумерованных фрагментов (номера 1-{count}), "
        "вырезанных с фотографии строительной площадки. Часть из них — не техника, "
        "это нормально и ожидаемо.\n\n"
        f"Для каждого номера выбери ровно один ключ из списка: "
        f"{json.dumps(options, ensure_ascii=False)}\n\n"
        "Правила, которые нельзя нарушать:\n"
        "1. По умолчанию фрагмент — НЕ техника. Класс техники ставь только тогда, "
        "когда машина узнаётся по характерным деталям (стрела и ковш, барабан, "
        "мачта буровой, отвал, кузов самосвала).\n"
        "2. Грузовик — это только крупный грузовой автомобиль. Легковая машина, "
        "микроавтобус, пикап и фургон доставки — это passenger_car.\n"
        "3. Длинный тонкий объект без корпуса машины — это cable_or_hose, а не "
        "стрела крана и не рукав бетононасоса.\n"
        "4. Если видна только часть машины и тип не читается — ставь not_equipment.\n\n"
        "Для каждого номера укажи также уверенность: high — тип машины виден однозначно; "
        "medium — скорее всего так, но есть сомнения; low — догадка.\n\n"
        "Отвечай строго одним JSON-объектом без текста вокруг:\n"
        '{"1": {"class": "ключ", "confidence": "high"}, "2": {"class": "ключ", "confidence": "low"}}'
    )

    buffer = io.BytesIO()
    grid.save(buffer, format="JPEG", quality=88)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    body = {
        "model": os.environ.get("AITUNNEL_VISION_MODEL", "claude-sonnet-4.6"),
        "max_tokens": 700,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                ],
            }
        ],
    }
    response = requests.post(
        f"{os.environ['AITUNNEL_BASE_URL']}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['AITUNNEL_API_KEY']}"},
        json=body,
        timeout=180,
    )
    if response.status_code != 200:
        print(f"    классификация не удалась: HTTP {response.status_code}")
        return {}

    content = response.json()["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        parsed = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return {}

    result: dict[int, tuple[str, str]] = {}
    for raw_key, raw_value in parsed.items():
        if not str(raw_key).isdigit():
            continue
        if isinstance(raw_value, dict):
            class_key = str(raw_value.get("class", "")).strip()
            confidence = str(raw_value.get("confidence", "low")).strip().lower()
        else:
            # Модель могла ответить старым плоским форматом — трактуем как догадку.
            class_key, confidence = str(raw_value).strip(), "low"
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        result[int(raw_key)] = (class_key, confidence)
    return result


def save_review_image(image: Image.Image, proposals: list[Proposal], labels: dict[str, str], path: Path) -> None:
    """Рисует итоговую разметку поверх снимка — для проверки глазами."""
    preview = image.copy()
    draw = ImageDraw.Draw(preview)
    font = _caption_font()
    for proposal in proposals:
        if proposal.assigned_key is None:
            continue
        x1, y1, x2, y2 = proposal.bbox
        draw.rectangle([x1, y1, x2, y2], outline=(255, 170, 0), width=3)
        caption = labels.get(proposal.assigned_key, proposal.assigned_key)
        text_box = draw.textbbox((0, 0), caption, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        # У высокой техники рамка начинается у самого верха кадра, и подпись
        # над ней оказывается за пределами изображения — тогда рисуем её внутри.
        caption_top = y1 - text_height - 7
        if caption_top < 0:
            caption_top = y1 + 2
        draw.rectangle(
            [x1, caption_top, x1 + text_width + 8, caption_top + text_height + 7],
            fill=(255, 170, 0),
        )
        draw.text((x1 + 4, caption_top + 2), caption, fill=(0, 0, 0), font=font)
    preview.thumbnail((1400, 1400))
    preview.save(path, quality=85)


def _describes_same_object(a: Proposal, b: Proposal) -> bool:
    """Описывают ли две рамки одну и ту же машину.

    Три признака, каждый ловит свой тип дубля:
    пересечение по площади — обычные смещённые дубли;
    вложенность — рамка на часть машины внутри рамки на всю машину;
    смежность по оси — у экскаватора одна рамка ложится на поднятую стрелу,
    вторая на корпус, они стоят вплотную и по площади почти не пересекаются.
    """
    intersection = _intersection_area(a.bbox, b.bbox)
    area_a, area_b = _area(a.bbox), _area(b.bbox)
    smaller = min(area_a, area_b)
    if smaller <= 0:
        return True

    if intersection > 0:
        union = area_a + area_b - intersection
        if union > 0 and intersection / union >= SAME_CLASS_IOU_THRESHOLD:
            return True
        if intersection / smaller >= SAME_CLASS_CONTAINMENT_THRESHOLD:
            return True

    if _center_inside(a.bbox, b.bbox) or _center_inside(b.bbox, a.bbox):
        return True

    # Смежность: сильное перекрытие по одной оси при малом зазоре по другой.
    horizontal_overlap = min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0])
    vertical_overlap = min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1])
    min_width = min(a.bbox[2] - a.bbox[0], b.bbox[2] - b.bbox[0])
    min_height = min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1])

    if min_width > 0 and horizontal_overlap >= 0.6 * min_width:
        vertical_gap = -vertical_overlap
        if vertical_gap <= 0.25 * min_height:
            return True

    if min_height > 0 and vertical_overlap >= 0.6 * min_height:
        horizontal_gap = -horizontal_overlap
        if horizontal_gap <= 0.25 * min_width:
            return True

    return False


def merge_same_class(proposals: list[Proposal]) -> list[Proposal]:
    """Объединяет рамки одного класса, описывающие один объект.

    Именно объединяет, а не отбрасывает лишние: когда одна рамка ловит
    стрелу, а другая корпус, ни одна из них по отдельности не описывает
    машину целиком — правильный ответ это их объединение.
    """
    order = {"high": 2, "medium": 1, "low": 0}
    merged = sorted(
        proposals,
        key=lambda p: (-order.get(p.assigned_confidence, 0), -p.confidence),
    )

    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                first, second = merged[i], merged[j]
                if first.assigned_key != second.assigned_key:
                    continue
                if not _describes_same_object(first, second):
                    continue
                merged[i] = Proposal(
                    bbox=(
                        min(first.bbox[0], second.bbox[0]),
                        min(first.bbox[1], second.bbox[1]),
                        max(first.bbox[2], second.bbox[2]),
                        max(first.bbox[3], second.bbox[3]),
                    ),
                    source_class=first.source_class,
                    confidence=max(first.confidence, second.confidence),
                    assigned_key=first.assigned_key,
                    assigned_confidence=(
                        first.assigned_confidence
                        if order.get(first.assigned_confidence, 0)
                        >= order.get(second.assigned_confidence, 0)
                        else second.assigned_confidence
                    ),
                )
                del merged[j]
                changed = True
                break
            if changed:
                break
    return merged


def process_image(
    image_path: Path,
    model,
    keys: list[str],
    labels: dict[str, str],
    min_confidence: str,
) -> int:
    raw_proposals = build_proposals(image_path, model)
    proposals = deduplicate(raw_proposals)
    # Мелкие рамки отсеиваются до обращения к модели: дешевле и честнее,
    # чем получать от неё угаданный класс по двадцати пикселям.
    proposals = [
        p
        for p in proposals
        if (p.bbox[2] - p.bbox[0]) >= MIN_BOX_SIDE_PX and (p.bbox[3] - p.bbox[1]) >= MIN_BOX_SIDE_PX
    ]
    if not proposals:
        print("    рамок не предложено")
        return 0

    with Image.open(image_path) as source:
        image = source.convert("RGB")
        crops = [crop_with_padding(image, p.bbox) for p in proposals]

        for start in range(0, len(crops), BATCH_SIZE):
            batch = crops[start : start + BATCH_SIZE]
            assignment = classify_grid(build_grid(batch), len(batch), labels)
            for offset in range(len(batch)):
                verdict = assignment.get(offset + 1)
                if verdict is None:
                    continue
                class_key, reported_confidence = verdict
                if class_key not in keys:
                    continue
                if not accepts_confidence(reported_confidence, min_confidence):
                    continue
                proposals[start + offset].assigned_key = class_key
                proposals[start + offset].assigned_confidence = reported_confidence
            time.sleep(0.4)

        accepted = merge_same_class([p for p in proposals if p.assigned_key is not None])
        proposals = [p for p in proposals if p.assigned_key is None] + accepted
        if accepted:
            lines = []
            for proposal in accepted:
                x1, y1, x2, y2 = proposal.bbox
                cx = ((x1 + x2) / 2) / image.width
                cy = ((y1 + y2) / 2) / image.height
                width = (x2 - x1) / image.width
                height = (y2 - y1) / image.height
                lines.append(
                    f"{keys.index(proposal.assigned_key)} {cx:.6f} {cy:.6f} {width:.6f} {height:.6f}"
                )
            (OUTPUT_DIR / f"{image_path.stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            target_image = OUTPUT_DIR / f"{image_path.stem}{image_path.suffix.lower()}"
            if not target_image.exists():
                image.save(target_image)
            save_review_image(image, proposals, labels, REVIEW_DIR / f"{image_path.stem}.jpg")

        rejected = len(proposals) - len(accepted)
        print(
            f"    рамок: предложено {len(raw_proposals)}, после дедупликации {len(proposals)}, "
            f"принято {len(accepted)}, отброшено как не техника {rejected}"
        )
        return len(accepted)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="обработать только первые N снимков")
    parser.add_argument(
        "--weights",
        default=str(ROOT / "models" / "yolov8s-worldv2.pt"),
        help="веса детектора для генерации рамок",
    )
    parser.add_argument(
        "--min-confidence",
        choices=["high", "medium", "low"],
        default=None,
        help="минимальная уверенность модели; по умолчанию берётся из настроек приложения",
    )
    args = parser.parse_args()

    if not os.environ.get("AITUNNEL_API_KEY"):
        print("не задан AITUNNEL_API_KEY — разметка невозможна")
        raise SystemExit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    min_confidence = args.min_confidence or read_min_confidence_from_settings()
    print(f"принимаем классы с уверенностью не ниже: {min_confidence}")

    keys, labels = load_taxonomy()

    from ultralytics import YOLOWorld

    model = YOLOWorld(args.weights)
    prompts = load_proposal_prompts()
    model.set_classes(prompts)
    print(f"промптов для генерации рамок: {len(prompts)}")

    images = sorted(p for p in IMAGES_DIR.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"})
    if args.limit:
        images = images[: args.limit]

    total_boxes = 0
    started = time.monotonic()
    for number, image_path in enumerate(images, start=1):
        print(f"[{number}/{len(images)}] {image_path.name}")
        total_boxes += process_image(image_path, model, keys, labels, min_confidence)

    elapsed = time.monotonic() - started
    print(f"\nразмечено рамок: {total_boxes} за {elapsed / 60:.1f} мин")
    print(f"разметка: {OUTPUT_DIR}")
    print(f"картинки для проверки глазами: {REVIEW_DIR}")


if __name__ == "__main__":
    main()
