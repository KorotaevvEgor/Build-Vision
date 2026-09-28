"""Группировка снимков по объектам: сколько площадок в выданном наборе.

Разбор датасета (scan_dataset.py) показал, что даты на кадрах выстраиваются в
съёмочные сессии: на одну дату приходится по 2-9 снимков. Это похоже на
ежемесячный обход, где фотографируют несколько объектов или несколько ракурсов
одного. Чтобы построить хронологию по объектам, надо сначала понять, где
кончается один объект и начинается другой.

Имя файла для этого не годится: нумерация скриншотов ничего не гарантирует.
Поэтому группируем по содержанию кадра — CLIP-эмбеддингу, который в проекте
уже используется классификатором-корректором. Снимки одной площадки с одной
точки съёмки похожи между собой сильно, снимки разных площадок — слабо.

Результат — предложение по разбиению, которое обязательно надо проверить
глазами: кластеризация по похожести не знает, что такое «объект», она знает
только, что кадры похожи.

Запуск:
    .venv\\Scripts\\python.exe scripts\\group_dataset.py
    .venv\\Scripts\\python.exe scripts\\group_dataset.py --threshold 0.82
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app import clip_embeddings, config

IMAGES_DIR = config.DATA_DIR / "raw" / "images"
SCAN_PATH = config.CONFIG_DIR / "dataset_scan.json"
OUTPUT_PATH = config.CONFIG_DIR / "dataset_groups.json"
EMBEDDINGS_PATH = config.DATA_DIR / "raw" / "clip_embeddings.json"


def _natural_key(name: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name))


def _cosine(a: list[float], b: list[float]) -> float:
    """Эмбеддинги уже L2-нормированы, поэтому косинус — это скалярное произведение."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def _load_embeddings(files: list[str]) -> dict[str, list[float]]:
    """Считает эмбеддинги с кэшем на диске: CLIP на процессоре не бесплатен."""
    cache: dict[str, list[float]] = {}
    if EMBEDDINGS_PATH.is_file():
        try:
            cache = json.loads(EMBEDDINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}

    missing = [name for name in files if name not in cache]
    for index, name in enumerate(missing, start=1):
        cache[name] = clip_embeddings.embed_image(IMAGES_DIR / name)
        if index % 10 == 0 or index == len(missing):
            print(f"  эмбеддинги: {index}/{len(missing)}")

    if missing:
        EMBEDDINGS_PATH.write_text(json.dumps(cache), encoding="utf-8")
    return cache


def _cluster(files: list[str], embeddings: dict[str, list[float]], threshold: float) -> list[list[str]]:
    """Связная кластеризация по порогу похожести.

    Намеренно самый простой алгоритм: объект — это множество кадров, связанных
    цепочкой похожести. Точка съёмки на стройке может медленно меняться от
    месяца к месяцу, поэтому связность по цепочке подходит лучше, чем
    требование, чтобы все кадры объекта были похожи на один центр.
    """
    parent = {name: name for name in files}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for i, left in enumerate(files):
        for right in files[i + 1 :]:
            if _cosine(embeddings[left], embeddings[right]) >= threshold:
                union(left, right)

    groups: dict[str, list[str]] = {}
    for name in files:
        groups.setdefault(find(name), []).append(name)
    return sorted(
        (sorted(members, key=_natural_key) for members in groups.values()),
        key=lambda members: -len(members),
    )


def run(threshold: float) -> int:
    if not SCAN_PATH.is_file():
        print(f"Нет разбора датасета: {SCAN_PATH}. Сначала scripts/scan_dataset.py")
        return 1

    scan = {item["file"]: item for item in json.loads(SCAN_PATH.read_text(encoding="utf-8"))["images"]}
    files = sorted(scan, key=_natural_key)
    print(f"Снимков: {len(files)}, порог похожести: {threshold}\n")

    embeddings = _load_embeddings(files)
    groups = _cluster(files, embeddings, threshold)

    payload = []
    print(f"\nНайдено групп: {len(groups)}\n")
    for index, members in enumerate(groups, start=1):
        dates = sorted(d for d in (scan[name]["observed_date"] for name in members) if d)
        stages: dict[str, int] = {}
        for name in members:
            label = scan[name]["stage_label"]
            stages[label] = stages.get(label, 0) + 1
        readiness = [
            scan[name]["readiness_percent"]
            for name in members
            if scan[name]["readiness_percent"] is not None
        ]

        period = f"{dates[0]} — {dates[-1]}" if dates else "без дат"
        top_stages = ", ".join(
            f"{label} ×{count}" for label, count in sorted(stages.items(), key=lambda kv: -kv[1])
        )
        print(f"Группа {index}: {len(members)} снимков, {len(dates)} с датой, период {period}")
        print(f"  готовность: {min(readiness, default='—')}% → {max(readiness, default='—')}%")
        print(f"  стадии: {top_stages}")
        print(f"  файлы: {', '.join(members[:12])}{' …' if len(members) > 12 else ''}\n")

        payload.append(
            {
                "group": index,
                "files": members,
                "dated_count": len(dates),
                "period_start": dates[0] if dates else None,
                "period_end": dates[-1] if dates else None,
                "stages": stages,
                "readiness_min": min(readiness) if readiness else None,
                "readiness_max": max(readiness) if readiness else None,
            }
        )

    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "note": (
                    "Предложение по разбиению выданных снимков на объекты. Получено "
                    "кластеризацией CLIP-эмбеддингов по цепочке похожести — это гипотеза, "
                    "которую надо проверить глазами, а не установленный факт."
                ),
                "threshold": threshold,
                "groups": payload,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Файл: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=0.85, help="Порог косинусной похожести")
    args = parser.parse_args()
    raise SystemExit(run(args.threshold))
