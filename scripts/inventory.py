"""Инвентаризация исходных снимков.

Что делает:
  1. Обходит data/raw/images, считает размер, разрешение, sha256 и dHash.
  2. Находит точные дубли (по sha256) и близкие кадры (по dHash).
  3. Группирует близкие кадры в "сцены" (один ракурс/площадка) методом union-find.
  4. Делит сцены на dev / val / holdout так, чтобы кадры одной сцены
     не попадали в разные части выборки.

Результаты:
  data/interim/manifest.csv   — построчная инвентаризация
  data/config/splits.json     — разбиение выборки по именам файлов

Запуск:
  python scripts/inventory.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = ROOT / "data" / "raw" / "images"
INTERIM_DIR = ROOT / "data" / "interim"
CONFIG_DIR = ROOT / "data" / "config"

# Порог расстояния Хэмминга между dHash, при котором кадры считаем одной сценой.
# Подобран консервативно: лучше объединить лишнее, чем разнести один ракурс
# по разным частям выборки и получить оптимистичную оценку качества.
SCENE_HAMMING_THRESHOLD = 14
SPLIT_TARGETS = {"dev": 0.6, "val": 0.2, "holdout": 0.2}
RANDOM_SEED = 20260914


@dataclass
class ImageRecord:
    file_name: str
    width: int
    height: int
    mode: str
    size_bytes: int
    sha256: str
    dhash: str
    mean_luma: float
    scene_id: int = -1
    duplicate_of: str = ""
    split: str = ""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dhash_of(image: Image.Image, hash_size: int = 8) -> int:
    """Разностный хеш: устойчив к масштабу и лёгкому изменению яркости."""
    small = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    bits = 0
    for row in range(hash_size):
        offset = row * (hash_size + 1)
        for col in range(hash_size):
            bits <<= 1
            if pixels[offset + col] > pixels[offset + col + 1]:
                bits |= 1
    return bits


def mean_luma_of(image: Image.Image) -> float:
    small = image.convert("L").resize((64, 64), Image.Resampling.BILINEAR)
    pixels = list(small.getdata())
    return round(sum(pixels) / len(pixels), 2)


def natural_key(name: str) -> tuple[str, int]:
    stem = Path(name).stem
    head, _, tail = stem.rpartition("_")
    return (head, int(tail)) if tail.isdigit() else (stem, 0)


def collect_records(paths: list[Path]) -> list[ImageRecord]:
    records: list[ImageRecord] = []
    for path in paths:
        with Image.open(path) as image:
            image.load()
            record = ImageRecord(
                file_name=path.name,
                width=image.width,
                height=image.height,
                mode=image.mode,
                size_bytes=path.stat().st_size,
                sha256=sha256_of(path),
                dhash=f"{dhash_of(image):016x}",
                mean_luma=mean_luma_of(image),
            )
        records.append(record)
    return records


def mark_exact_duplicates(records: list[ImageRecord]) -> None:
    first_seen: dict[str, str] = {}
    for record in records:
        original = first_seen.setdefault(record.sha256, record.file_name)
        if original != record.file_name:
            record.duplicate_of = original


def group_scenes(records: list[ImageRecord]) -> None:
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    hashes = [int(record.dhash, 16) for record in records]
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if (hashes[i] ^ hashes[j]).bit_count() <= SCENE_HAMMING_THRESHOLD:
                union(i, j)

    scene_ids: dict[int, int] = {}
    for index, record in enumerate(records):
        root = find(index)
        record.scene_id = scene_ids.setdefault(root, len(scene_ids))


def assign_splits(records: list[ImageRecord]) -> dict[str, list[str]]:
    """Раскладываем сцены целиком, приближаясь к целевым долям по числу кадров."""
    scenes: dict[int, list[ImageRecord]] = defaultdict(list)
    for record in records:
        scenes[record.scene_id].append(record)

    ordered = sorted(scenes.values(), key=lambda group: (-len(group), group[0].file_name))
    random.Random(RANDOM_SEED).shuffle(ordered)
    ordered.sort(key=len, reverse=True)

    total = len(records)
    quota = {name: share * total for name, share in SPLIT_TARGETS.items()}
    assigned: dict[str, list[ImageRecord]] = {name: [] for name in SPLIT_TARGETS}

    for group in ordered:
        target = max(quota, key=lambda name: quota[name] - len(assigned[name]))
        assigned[target].extend(group)

    for split_name, group in assigned.items():
        for record in group:
            record.split = split_name

    return {
        name: sorted((r.file_name for r in group), key=natural_key)
        for name, group in assigned.items()
    }


def main() -> None:
    if not IMAGES_DIR.exists():
        raise SystemExit(f"Каталог со снимками не найден: {IMAGES_DIR}")

    paths = sorted(IMAGES_DIR.glob("*.png"), key=lambda p: natural_key(p.name))
    if not paths:
        raise SystemExit(f"В {IMAGES_DIR} нет PNG-файлов")

    records = collect_records(paths)
    mark_exact_duplicates(records)
    group_scenes(records)
    splits = assign_splits(records)

    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    manifest_path = INTERIM_DIR / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(records[0]).keys()))
        writer.writeheader()
        for record in sorted(records, key=lambda r: natural_key(r.file_name)):
            writer.writerow(asdict(record))

    splits_path = CONFIG_DIR / "splits.json"
    splits_payload = {
        "seed": RANDOM_SEED,
        "scene_hamming_threshold": SCENE_HAMMING_THRESHOLD,
        "note": "Кадры одной сцены не разделяются между частями выборки.",
        "splits": splits,
    }
    splits_path.write_text(
        json.dumps(splits_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    scene_sizes = defaultdict(int)
    for record in records:
        scene_sizes[record.scene_id] += 1
    duplicates = [r for r in records if r.duplicate_of]
    resolutions = defaultdict(int)
    for record in records:
        resolutions[f"{record.width}x{record.height}"] += 1

    print(f"Снимков: {len(records)}")
    print(f"Точных дублей: {len(duplicates)}")
    print(f"Сцен (групп близких кадров): {len(scene_sizes)}")
    print("Крупнейшие сцены:", sorted(scene_sizes.values(), reverse=True)[:10])
    print("Разрешения:", dict(sorted(resolutions.items(), key=lambda kv: -kv[1])))
    print("Разбиение:", {name: len(files) for name, files in splits.items()})
    print(f"Манифест: {manifest_path}")
    print(f"Разбиение: {splits_path}")


if __name__ == "__main__":
    main()
