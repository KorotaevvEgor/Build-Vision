"""Сборка единого обучающего набора YOLO из разнородных открытых источников.

Источники приходят в разных раскладках и с разными именами классов, поэтому
их нельзя просто сложить в одну папку: номера классов у них конфликтуют.
Скрипт приводит всё к нашей таксономии (`ml/taxonomy.yaml`), переиндексирует
классы и раскладывает по train/val.

Принципиальное правило: класс источника, которого нет в таблице сопоставления,
отбрасывается вместе с рамкой, а не подменяется «похожим». Молчаливая подмена
порождает скрытые ошибки разметки, которые потом невозможно отследить по
метрикам — именно так появляются модели, уверенно называющие трубы самосвалами.

Запуск:
    .venv-ml\\Scripts\\python.exe ml\\prepare_dataset.py --val-fraction 0.15
"""

from __future__ import annotations

import argparse
import random
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = ROOT / "ml" / "taxonomy.yaml"
SOURCES_ROOT = ROOT / "data" / "datasets"
OUTPUT_ROOT = ROOT / "data" / "datasets" / "unified"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class Taxonomy:
    keys: list[str]
    labels_ru: dict[str, str]

    def index_of(self, key: str) -> int:
        return self.keys.index(key)


def load_taxonomy() -> tuple[Taxonomy, dict]:
    data = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))
    keys = [item["key"] for item in data["classes"]]
    labels = {item["key"]: item["label_ru"] for item in data["classes"]}
    return Taxonomy(keys=keys, labels_ru=labels), data.get("sources", {})


def _source_class_names(source_dir: Path) -> list[str] | None:
    """Читает имена классов из data.yaml, если источник его содержит."""
    for candidate in ("data.yaml", "data.yml"):
        path = source_dir / candidate
        if path.is_file():
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            names = payload.get("names")
            if isinstance(names, dict):
                return [names[key] for key in sorted(names, key=int)]
            if isinstance(names, list):
                return names
    return None


def _iter_image_label_pairs(source_dir: Path) -> list[tuple[Path, Path]]:
    """Находит пары «изображение — разметка» независимо от раскладки источника.

    Поддерживаются и плоская папка (1.jpg рядом с 1.txt), и стандартная
    раскладка YOLO с каталогами images/ и labels/.
    """
    pairs: list[tuple[Path, Path]] = []
    for image_path in sorted(source_dir.rglob("*")):
        if image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        label_path = image_path.with_suffix(".txt")
        if not label_path.is_file():
            # Стандартная раскладка YOLO: .../images/x.jpg -> .../labels/x.txt
            parts = list(image_path.parts)
            if "images" in parts:
                parts[len(parts) - 1 - parts[::-1].index("images")] = "labels"
                label_path = Path(*parts).with_suffix(".txt")
        if label_path.is_file():
            pairs.append((image_path, label_path))
    return pairs


def _remap_label_file(
    label_path: Path,
    class_map: dict[str, str],
    source_names: list[str] | None,
    taxonomy: Taxonomy,
) -> list[str]:
    """Переиндексирует строки разметки под нашу таксономию.

    Возвращает готовые строки. Рамки неизвестных классов отбрасываются.
    """
    remapped: list[str] = []
    for raw_line in label_path.read_text(encoding="utf-8").splitlines():
        parts = raw_line.split()
        if len(parts) < 5:
            continue
        source_index = parts[0]
        source_name = None
        if source_names is not None:
            try:
                source_name = source_names[int(source_index)].strip().lower()
            except (ValueError, IndexError):
                source_name = None

        target_key = class_map.get(source_index)
        if target_key is None and source_name is not None:
            target_key = class_map.get(source_name)
        if target_key is None or target_key not in taxonomy.labels_ru:
            continue

        remapped.append(" ".join([str(taxonomy.index_of(target_key)), *parts[1:5]]))
    return remapped


def build(val_fraction: float, seed: int) -> None:
    taxonomy, sources = load_taxonomy()

    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    for split in ("train", "val"):
        (OUTPUT_ROOT / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUTPUT_ROOT / "labels" / split).mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    per_class_counts: dict[str, int] = {}
    total_images = 0
    skipped_without_boxes = 0

    for source_key, source in sources.items():
        source_dir = SOURCES_ROOT / source["path"]
        if not source_dir.is_dir():
            print(f"пропуск источника {source_key}: каталог не найден ({source_dir})")
            continue

        class_map = {str(k).strip().lower(): v for k, v in source["class_map"].items()}
        source_names = _source_class_names(source_dir)
        pairs = _iter_image_label_pairs(source_dir)
        print(f"источник {source_key}: найдено пар изображение/разметка — {len(pairs)}")

        for image_path, label_path in pairs:
            lines = _remap_label_file(label_path, class_map, source_names, taxonomy)
            if not lines:
                # Кадр, на котором не осталось ни одной рамки нашей таксономии,
                # в обучение не идёт: он не несёт сигнала, но вносит дисбаланс.
                skipped_without_boxes += 1
                continue

            split = "val" if rng.random() < val_fraction else "train"
            stem = f"{source_key}_{image_path.stem}"
            shutil.copy2(image_path, OUTPUT_ROOT / "images" / split / f"{stem}{image_path.suffix.lower()}")
            (OUTPUT_ROOT / "labels" / split / f"{stem}.txt").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
            total_images += 1
            for line in lines:
                key = taxonomy.keys[int(line.split()[0])]
                per_class_counts[key] = per_class_counts.get(key, 0) + 1

    data_yaml = {
        "path": str(OUTPUT_ROOT).replace("\\", "/"),
        "train": "images/train",
        "val": "images/val",
        "names": dict(enumerate(taxonomy.keys)),
    }
    (OUTPUT_ROOT / "data.yaml").write_text(
        yaml.safe_dump(data_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    print(f"\nитого изображений: {total_images}")
    print(f"кадров без рамок нашей таксономии (пропущено): {skipped_without_boxes}")
    print("рамок по классам:")
    for key in taxonomy.keys:
        count = per_class_counts.get(key, 0)
        marker = "  (нет данных)" if count == 0 else ""
        print(f"  {taxonomy.labels_ru[key]:26s} {count:6d}{marker}")
    print(f"\nописание набора: {OUTPUT_ROOT / 'data.yaml'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--val-fraction", type=float, default=0.15, help="доля кадров в валидации")
    parser.add_argument("--seed", type=int, default=20260925, help="зерно случайного разбиения")
    args = parser.parse_args()
    build(val_fraction=args.val_fraction, seed=args.seed)


if __name__ == "__main__":
    main()
