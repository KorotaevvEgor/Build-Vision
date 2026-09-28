"""Разбор всего выданного набора снимков: стадия, готовность, дата со штампа.

Зачем. Пока в системе лежат несколько наблюдений, налитых вручную, смотреть
в ней не на что: любой экран показывает пустоту, а надзорный орган работает
не с одним кадром, а с историей объекта за месяцы. Этот скрипт превращает
100 статичных файлов в исходные данные для такой истории.

Ключевая находка, ради которой он написан: в выданные кадры впечатан штамп
даты, и модель его читает. Значит хронологию объектов не нужно выдумывать —
её можно восстановить из самих снимков.

Результат пишется в data/config/dataset_scan.json. Ответы модели кэшируются
по SHA-256 файла, поэтому повторный запуск почти бесплатен и его не страшно
перезапускать.

Запуск:
    .venv\\Scripts\\python.exe scripts\\scan_dataset.py
    .venv\\Scripts\\python.exe scripts\\scan_dataset.py --workers 6
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app import config
from app.llm import assess_photo, llm_is_configured

IMAGES_DIR = config.DATA_DIR / "raw" / "images"
OUTPUT_PATH = config.CONFIG_DIR / "dataset_scan.json"

_DATE_RE = re.compile(r"^(\d{2})[.\-/](\d{2})[.\-/](\d{4})$")


def _natural_key(path: Path) -> tuple:
    """Сортировка Screenshot_2 перед Screenshot_10, а не наоборот."""
    return tuple(
        int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.name)
    )


def _parse_date(raw: str | None) -> str | None:
    """Приводит штамп к ISO. Неразобранный штамп — не дата, а мусор, и он отбрасывается.

    Отдельно отсекаются заведомо невозможные годы: модель иногда принимает за
    дату номер или подпись на кадре, и такую «дату» нельзя пускать в хронологию.
    """
    if not raw:
        return None
    match = _DATE_RE.match(raw.strip())
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    if not (2000 <= year <= 2030):
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def scan_one(image: Path) -> dict:
    assessment = assess_photo(image)
    return {
        "file": image.name,
        "available": assessment.available,
        "stage_key": assessment.stage_key,
        "stage_label": assessment.stage_label,
        "readiness_percent": assessment.readiness_percent,
        "confidence": assessment.confidence,
        "date_stamp_raw": assessment.date_stamp,
        "observed_date": _parse_date(assessment.date_stamp),
        "visual_evidence": assessment.visual_evidence,
        "equipment": assessment.equipment,
        "cached": assessment.cached,
        "error": assessment.error,
    }


def run(workers: int) -> int:
    if not IMAGES_DIR.is_dir():
        print(f"Нет каталога со снимками: {IMAGES_DIR}")
        return 1
    if not llm_is_configured():
        print("Ключ AITUNNEL_API_KEY не задан — разбор невозможен.")
        return 1

    images = sorted(IMAGES_DIR.glob("*.png"), key=_natural_key)
    print(f"Снимков к разбору: {len(images)}, потоков: {workers}\n")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan_one, image): image for image in images}
        for done, future in enumerate(as_completed(futures), start=1):
            item = future.result()
            results.append(item)
            mark = "кэш" if item["cached"] else "запрос"
            if item["available"]:
                print(
                    f"[{done:3d}/{len(images)}] {item['file']:20s} {item['stage_label'][:42]:42s} "
                    f"{str(item['readiness_percent']) + '%':>5s} {item['observed_date'] or '—':10s} ({mark})"
                )
            else:
                print(f"[{done:3d}/{len(images)}] {item['file']:20s} НЕ РАЗОБРАН: {item['error']}")

    results.sort(key=lambda item: _natural_key(Path(item["file"])))
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "note": (
                    "Результат разбора выданного набора снимков моделью: стадия, оценка "
                    "готовности и дата, прочитанная со штампа на кадре. Используется для "
                    "восстановления хронологии объектов — даты не выдуманы, а взяты с самих фото."
                ),
                "images": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    ok = [item for item in results if item["available"]]
    dated = [item for item in ok if item["observed_date"]]
    print(f"\nРазобрано {len(ok)} из {len(results)}, с датой на кадре — {len(dated)}.")

    print("\nСтадии:")
    for label, count in Counter(item["stage_label"] for item in ok).most_common():
        print(f"  {count:3d}  {label}")

    if dated:
        years = Counter(item["observed_date"][:4] for item in dated)
        print("\nГоды по штампам:")
        for year, count in sorted(years.items()):
            print(f"  {count:3d}  {year}")
        print("\nХронология (дата — стадия — готовность — файл):")
        for item in sorted(dated, key=lambda i: i["observed_date"]):
            print(
                f"  {item['observed_date']}  {item['stage_label'][:38]:38s} "
                f"{str(item['readiness_percent']) + '%':>5s}  {item['file']}"
            )

    print(f"\nФайл: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=5, help="Параллельных запросов к модели")
    args = parser.parse_args()
    raise SystemExit(run(max(1, min(args.workers, 8))))
