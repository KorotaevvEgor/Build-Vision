"""Базовый замер детектора YOLO-World на CPU.

Цель — получить честную отправную точку до какой-либо разработки интерфейса:
что модель вообще видит на этих кадрах, сколько времени и памяти это стоит.

Скрипт не оценивает precision/recall: разметки пока нет. Он сохраняет
визуализации и JSON, чтобы результаты можно было просмотреть вручную
и уже после этого решать, годится ли модель без дообучения.

Запуск:
  python scripts/baseline_detect.py --limit 20 --split dev
  python scripts/baseline_detect.py --imgsz 1280 --conf 0.05 --tag hi-res
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Кэши держим вне системного диска: он почти заполнен.
os.environ.setdefault("YOLO_CONFIG_DIR", str(Path("D:/dev/caches/ultralytics")))
os.environ.setdefault("TORCH_HOME", str(Path("D:/dev/caches/torch")))

import psutil
import yaml
from PIL import Image, ImageDraw, ImageFont

IMAGES_DIR = ROOT / "data" / "raw" / "images"
CONFIG_DIR = ROOT / "data" / "config"
RUNS_DIR = ROOT / "data" / "runs"
WEIGHTS_DIR = ROOT / "models"

DEFAULT_WEIGHTS = "yolov8s-worldv2.pt"

# Шрифт по умолчанию в Pillow не содержит кириллицы — подписи превращаются в квадраты.
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def load_font(size: int = 14) -> ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def load_vocabulary(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    """Возвращает плоский список промптов и карту промпт → класс."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    prompts: list[str] = []
    prompt_to_class: dict[str, dict[str, str]] = {}
    for group, in_taxonomy in (("classes", True), ("distractors", False)):
        for entry in data.get(group) or []:
            for prompt in entry["prompts"]:
                prompts.append(prompt)
                prompt_to_class[prompt] = {
                    "key": entry["key"],
                    "label_ru": entry["label_ru"],
                    "in_taxonomy": in_taxonomy,
                }
    return prompts, prompt_to_class


def select_images(split: str, limit: int) -> list[Path]:
    splits_path = CONFIG_DIR / "splits.json"
    if not splits_path.exists():
        raise SystemExit("Сначала выполните scripts/inventory.py")
    payload = json.loads(splits_path.read_text(encoding="utf-8"))
    names = payload["splits"][split] if split != "all" else sorted(
        name for group in payload["splits"].values() for name in group
    )
    if limit > 0 and limit < len(names):
        # Равномерная выборка по списку, а не первые N подряд:
        # нужны разные площадки, сезоны и ракурсы.
        step = len(names) / limit
        names = [names[int(i * step)] for i in range(limit)]
    return [IMAGES_DIR / name for name in names]


def draw_detections(image_path: Path, detections: list[dict], output_path: Path) -> None:
    font = load_font()
    with Image.open(image_path) as image:
        canvas = image.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            color = (11, 122, 117) if det["in_taxonomy"] else (150, 150, 150)
            draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
            caption = f"{det['label_ru']} {det['confidence']:.2f}"
            anchor = (x1, max(0, y1 - 18))
            text_box = draw.textbbox(anchor, caption, font=font)
            draw.rectangle(text_box, fill=color)
            draw.text(anchor, caption, fill=(255, 255, 255), font=font)
        canvas.save(output_path, quality=85)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=["dev", "val", "holdout", "all"])
    parser.add_argument("--limit", type=int, default=20, help="0 — без ограничения")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.50)
    parser.add_argument("--max-det", type=int, default=60)
    parser.add_argument(
        "--per-class-nms",
        action="store_true",
        help="Отключить класс-агностичный NMS. По умолчанию он включён: несколько "
        "промптов одного и того же объекта иначе дают десятки вложенных рамок.",
    )
    parser.add_argument("--weights", default=DEFAULT_WEIGHTS)
    parser.add_argument("--tag", default="", help="Суффикс каталога с результатами")
    args = parser.parse_args()

    prompts, prompt_to_class = load_vocabulary(CONFIG_DIR / "vocabulary.yaml")
    images = select_images(args.split, args.limit)
    if not images:
        raise SystemExit("Не выбрано ни одного изображения")

    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    weights_path = WEIGHTS_DIR / args.weights

    from ultralytics import YOLOWorld  # импорт здесь: он долгий

    load_started = time.perf_counter()
    # Путь указываем полностью: иначе ultralytics скачает веса в текущий каталог.
    model = YOLOWorld(str(weights_path))
    model.set_classes(prompts)
    load_seconds = time.perf_counter() - load_started

    process = psutil.Process()
    baseline_rss = process.memory_info().rss
    peak_rss = baseline_rss

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_name = f"{stamp}-{args.split}-{args.imgsz}px" + (f"-{args.tag}" if args.tag else "")
    run_dir = RUNS_DIR / "baseline" / run_name
    vis_dir = run_dir / "vis"
    vis_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    durations: list[float] = []
    class_counts: dict[str, int] = {}

    for index, image_path in enumerate(images, start=1):
        started = time.perf_counter()
        result = model.predict(
            source=str(image_path),
            imgsz=args.imgsz,
            conf=args.conf,
            iou=args.iou,
            max_det=args.max_det,
            agnostic_nms=not args.per_class_nms,
            device="cpu",
            verbose=False,
        )[0]
        elapsed = time.perf_counter() - started
        durations.append(elapsed)
        peak_rss = max(peak_rss, process.memory_info().rss)

        names = result.names
        detections: list[dict] = []
        for box in result.boxes:
            prompt = names[int(box.cls.item())]
            meta = prompt_to_class[prompt]
            detections.append(
                {
                    "prompt": prompt,
                    "class_key": meta["key"],
                    "label_ru": meta["label_ru"],
                    "in_taxonomy": meta["in_taxonomy"],
                    "confidence": round(float(box.conf.item()), 4),
                    "bbox": [round(float(v), 1) for v in box.xyxy[0].tolist()],
                }
            )
            class_counts[meta["key"]] = class_counts.get(meta["key"], 0) + 1

        detections.sort(key=lambda d: -d["confidence"])
        draw_detections(image_path, detections, vis_dir / f"{image_path.stem}.jpg")
        records.append(
            {
                "file_name": image_path.name,
                "seconds": round(elapsed, 3),
                "detections": detections,
            }
        )
        print(
            f"[{index}/{len(images)}] {image_path.name}: "
            f"{len(detections)} рамок за {elapsed:.2f} c"
        )

    ordered = sorted(durations)
    summary = {
        "run": run_name,
        "weights": args.weights,
        "imgsz": args.imgsz,
        "conf": args.conf,
        "iou": args.iou,
        "max_det": args.max_det,
        "agnostic_nms": not args.per_class_nms,
        "split": args.split,
        "images": len(images),
        "prompts": len(prompts),
        "model_load_seconds": round(load_seconds, 2),
        "seconds_per_image": {
            "first": round(durations[0], 2),
            "median": round(ordered[len(ordered) // 2], 2),
            "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2),
            "max": round(ordered[-1], 2),
        },
        "rss_mb": {
            "after_load": round(baseline_rss / 1024 / 1024, 1),
            "peak": round(peak_rss / 1024 / 1024, 1),
        },
        "detections_total": sum(len(r["detections"]) for r in records),
        "detections_by_class": dict(sorted(class_counts.items(), key=lambda kv: -kv[1])),
        "images_without_detections": [r["file_name"] for r in records if not r["detections"]],
    }

    (run_dir / "detections.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nВизуализации: {vis_dir}")


if __name__ == "__main__":
    main()
