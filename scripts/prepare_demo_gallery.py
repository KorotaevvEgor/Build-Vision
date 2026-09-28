"""Сборка демонстрационной выборки и прогрев кэша языковой модели.

Оценка на защите будет экспертной, на наших же примерах, с явным вниманием
к разнообразию: сезоны, стадии, количество техники. Поэтому выборка
собирается заранее и осознанно, а не «первые пятнадцать файлов».

Скрипт делает две вещи:

1. прогоняет выбранные снимки через оценку стадии по фотографии, чтобы
   ответ лёг в кэш по SHA-256 файла. На показе он вернётся за доли секунды
   и не будет зависеть от интернета в зале;
2. записывает перечень в data/config/demo_gallery.json, откуда его берёт
   публичный демонстрационный экран.

Запуск:
    .venv\\Scripts\\python.exe scripts\\prepare_demo_gallery.py
    .venv\\Scripts\\python.exe scripts\\prepare_demo_gallery.py --no-warm
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app import config, demo
from app.llm import llm_is_configured

IMAGES_DIR = config.DATA_DIR / "raw" / "images"
MANIFEST_PATH = config.CONFIG_DIR / "demo_gallery.json"

#: Кадры выборки. Подписей содержания здесь нет намеренно: что именно на
#: снимке, определяет сама система при прогреве, и именно её ответ попадает в
#: манифест. Подписать кадр «Снегопад» заранее, не глядя, значило бы показывать
#: жюри свою догадку вместо результата работы системы.
#:
#: Состав отобран после прогона 24 кадров через весь набор — по фактически
#: определённым стадиям, а не по догадке. Важный факт о самих данных: выданные
#: 100 снимков сильно смещены в ранние стадии (преобладают свайные работы), и
#: выборка показывает все найденные стадии, а не делает вид, что набор ровный.
#: Отдельно взяты кадры без штампа даты: на них видно, как система честно
#: сообщает об отсутствии даты, а не подставляет сегодняшнюю.
SAMPLE_FILES: list[str] = [
    # Самая высокая готовность в наборе и самая поздняя стадия.
    "Screenshot_1.png",
    # Начальные стадии: подготовка территории в разные годы.
    "Screenshot_25.png",
    "Screenshot_60.png",
    # Земляные работы в трёх разных сезонах по штампу даты.
    "Screenshot_12.png",
    "Screenshot_48.png",
    "Screenshot_66.png",
    # Свайные работы разных лет и сезонов — основной содержательный пласт набора.
    "Screenshot_5.png",
    "Screenshot_10.png",
    "Screenshot_28.png",
    "Screenshot_42.png",
    "Screenshot_20.png",
    # Монолитные работы ниже отметки ноль.
    "Screenshot_95.png",
    "Screenshot_100.png",
    # Кадр без штампа даты.
    "Screenshot_55.png",
]


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def build(warm: bool) -> int:
    if not IMAGES_DIR.is_dir():
        print(f"Нет каталога со снимками: {IMAGES_DIR}")
        return 1

    if warm and not llm_is_configured():
        print("Ключ языковой модели не настроен — выборка соберётся без прогрева кэша.")
        warm = False

    entries: list[dict] = []
    missing: list[str] = []

    for index, file_name in enumerate(SAMPLE_FILES, start=1):
        image = IMAGES_DIR / file_name
        if not image.is_file():
            missing.append(file_name)
            continue

        entry = {
            "id": f"sample-{index:02d}",
            # До прогрева честное название — имя файла; после — определённая стадия.
            "title": file_name,
            "season": "",
            "scenario": "",
            "path": image.relative_to(config.ROOT).as_posix(),
            "warmed": False,
        }

        if warm:
            # Прогрев идёт ровно тем же путём, что и публичный эндпоинт, включая
            # детектор. Иначе состав техники в запросе комментария отличается, ключ
            # кэша не совпадает, и на показе всё равно уходит живой запрос.
            analysis = demo.analyze(image, _file_digest(image))
            vision = analysis.get("vision") or {}
            if vision.get("available"):
                entry["title"] = vision["stage_label"]
                entry["scenario"] = "; ".join(vision["visual_evidence"][:2])
                entry["stage_label"] = vision["stage_label"]
                entry["readiness_percent"] = vision["readiness_percent"]
                entry["date_stamp"] = vision["date_stamp"]
                entry["warmed"] = bool(analysis["comment"].get("available"))
                equipment = ", ".join(
                    f"{e['label_ru']}×{e['count']}" for e in analysis["equipment_counts"]
                )
                print(
                    f"  {entry['id']} ({file_name}): {vision['stage_label']}, "
                    f"готовность {vision['readiness_percent']}%, "
                    f"штамп {vision['date_stamp'] or '—'}, техника: {equipment or 'нет'}"
                )
            else:
                print(f"  {entry['id']} ({file_name}): оценка недоступна ({vision.get('error')})")

        entries.append(entry)

    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "note": (
                    "Демонстрационная выборка для публичного экрана. Кадры взяты равномерно по "
                    "всему выданному набору, а стадия, готовность и признаки записаны по "
                    "фактическому ответу системы при прогреве кэша, а не проставлены вручную."
                ),
                "samples": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    warmed = sum(1 for e in entries if e["warmed"])
    print(f"\nВ выборке {len(entries)} снимков, прогрето {warmed}. Файл: {MANIFEST_PATH}")
    if missing:
        print(f"Не найдены и пропущены: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-warm",
        action="store_true",
        help="Только собрать перечень, не обращаясь к языковой модели",
    )
    args = parser.parse_args()
    raise SystemExit(build(warm=not args.no_warm))
