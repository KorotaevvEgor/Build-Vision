"""Готовит пакет для демонстрации: часть кадров таймлапса + календарный план.

Что делает:
1. Берёт первую 1/5 часть кадров (котлован + начало стройки, не финал).
2. Для кадров, где виден вшитый в видео штамп даты/времени камеры (это только
   самое начало ролика — примерно первые 225 кадров из отобранных 720),
   закрашивает старый штамп и рисует новый, чтобы даты выглядели как
   август–ноябрь текущего года, а не как реальная дата съёмки видео (2020).
3. Пишет data/уровня календарный план (.xlsx) в формате, который понимает
   backend/app/schedule_import.py — те же колонки, что генерирует
   «Скачать шаблон» на странице создания проекта.
4. Пишет CSV с датой, которую стоит указывать при загрузке каждого фото
   («Дата съёмки» в форме анализа/наблюдения).

Использование:
    python scripts/prepare_demo_upload.py
"""

from __future__ import annotations

import csv
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

# --- Исходные данные ---------------------------------------------------

SOURCE_DIR = Path(
    r"C:\Users\catoa\Downloads\Часовой таймлапс строительство многоквартирного дома - EkbIT (1080p, h264)_frames"
)
OUTPUT_ROOT = Path(r"C:\Users\catoa\Downloads\demo_upload")
PHOTOS_OUT = OUTPUT_ROOT / "photos"

TOTAL_FRAMES = 3600
# Первая 1/5 всего ролика — котлован + начало каркаса, без финальных кадров.
SELECTED_COUNT = TOTAL_FRAMES // 5  # 720

# Видимый штамп даты/времени камеры есть только в первых кадрах ролика
# (одна и та же вводная сцена котлована); дальше идут другие камеры без
# штампа. Определено визуальным просмотром кадров 1..350 с шагом ~10-50.
STAMPED_FRAME_LIMIT = 225

# Новый «текущий» период для демонстрации.
DEMO_START = date(2026, 8, 1)
DEMO_PHOTOS_END = date(2026, 10, 9)  # конец видимого в этой партии этапа (стадии 1-4)
DEMO_PROJECT_END = date(2026, 11, 30)  # конец графика целиком (для календарного плана)

TEMPLATE_COLUMNS = [
    "№",
    "Код работы",
    "Наименование работ",
    "Зона",
    "Дата начала",
    "Дата окончания",
    "№ родительской работы",
    "№ предшественников",
    "Технологическое допущение",
]

# Колонка сверх стандартного шаблона — парсер импорта (schedule_import.py)
# читает только первые len(TEMPLATE_COLUMNS) ячеек строки и её игнорирует,
# так что формат импорта не ломается. Нужна как памятка для человека и как
# заготовка для настройки штатной проверки план/факт (StageRule.required_items
# в Django admin) — там количество техники привязывается к ключу класса
# словаря (data/config/vocabulary.yaml), а не к тексту допущения.
EXTRA_COLUMN_TITLE = "Необходимая техника, шт. (класс словаря)"

# label_ru по ключам словаря — см. data/config/vocabulary.yaml.
CLASS_LABELS_RU = {
    "excavator": "Экскаватор",
    "dump_truck": "Самосвал",
    "truck": "Грузовик",
    "mobile_crane": "Автокран",
    "concrete_mixer": "Автобетоносмеситель",
    "crane_manipulator": "Кран-манипулятор",
    "road_roller": "Каток",
    "bulldozer": "Бульдозер",
}

ZONE_NAME = "Площадка"


def _format_quantities(quantities: dict[str, int]) -> str:
    return "; ".join(
        f"{CLASS_LABELS_RU[key]} ({key}) — {qty} шт." for key, qty in quantities.items()
    )


def _tech_text(quantities: dict[str, int], extra_note: str = "") -> str:
    parts = [f"{CLASS_LABELS_RU[key]} — {qty} шт." for key, qty in quantities.items()]
    text = "; ".join(parts) + "."
    return f"{text} {extra_note}".strip()


STAGES: list[dict] = [
    dict(
        work_name="Подготовительные работы (ограждение, снос старых построек)",
        start=date(2026, 8, 1),
        end=date(2026, 8, 7),
        quantities={"excavator": 1, "truck": 2},
    ),
    dict(
        work_name="Устройство котлована",
        start=date(2026, 8, 8),
        end=date(2026, 8, 21),
        quantities={"excavator": 2, "dump_truck": 3},
    ),
    dict(
        work_name="Устройство фундаментной плиты",
        start=date(2026, 8, 22),
        end=date(2026, 9, 11),
        quantities={"mobile_crane": 1, "concrete_mixer": 3, "excavator": 1},
    ),
    dict(
        work_name="Монолитный каркас (этажи 1–5)",
        start=date(2026, 9, 12),
        end=date(2026, 10, 9),
        quantities={"mobile_crane": 1, "concrete_mixer": 2},
        extra_note="Кран — башенный (учитывается классом «Автокран»).",
    ),
    dict(
        work_name="Монолитный каркас (этажи 6–10) и кирпичная кладка нижних этажей",
        start=date(2026, 10, 10),
        end=date(2026, 10, 30),
        quantities={"mobile_crane": 2, "concrete_mixer": 2, "crane_manipulator": 1},
    ),
    dict(
        work_name="Кирпичная кладка верхних этажей, устройство фасада",
        start=date(2026, 10, 31),
        end=date(2026, 11, 13),
        quantities={"mobile_crane": 2, "crane_manipulator": 2},
    ),
    dict(
        work_name="Остекление и отделка фасада",
        start=date(2026, 11, 14),
        end=date(2026, 11, 30),
        quantities={"mobile_crane": 1, "crane_manipulator": 2},
    ),
]

for _stage in STAGES:
    _stage["tech"] = _tech_text(_stage["quantities"], _stage.get("extra_note", ""))


def imwrite_unicode(path: Path, frame, quality: int = 95) -> bool:
    """cv2.imwrite молча не пишет файлы по путям с не-ASCII символами на Windows —
    кодируем в память и пишем сами через numpy.tofile()."""
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return False
    buf.tofile(str(path))
    return True


def draw_fake_timestamp(frame, when: datetime):
    """Закрашивает старый штамп даты в правом верхнем углу и рисует новый —
    тот же угол экрана и похожий стиль (белый текст с чёрной обводкой)."""
    h, w = frame.shape[:2]
    # Область штампа определена по факту в кадрах 1920x1080; масштабируем,
    # если разрешение кадра вдруг другое.
    scale_x, scale_y = w / 1920, h / 1080
    x1, y1, x2, y2 = 1320, 5, 1910, 95
    x1, x2 = int(x1 * scale_x), int(x2 * scale_x)
    y1, y2 = int(y1 * scale_y), int(y2 * scale_y)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (10, 10, 10), thickness=-1)

    text = when.strftime("%d-%m-%Y %H:%M:%S")
    font = cv2.FONT_HERSHEY_DUPLEX
    font_scale = 1.15 * min(scale_x, scale_y)
    thickness_outline = max(1, round(5 * min(scale_x, scale_y)))
    thickness_fill = max(1, round(2 * min(scale_x, scale_y)))
    origin = (x1 + int(10 * scale_x), y2 - int(20 * scale_y))
    cv2.putText(frame, text, origin, font, font_scale, (0, 0, 0), thickness_outline, cv2.LINE_AA)
    cv2.putText(frame, text, origin, font, font_scale, (255, 255, 255), thickness_fill, cv2.LINE_AA)
    return frame


def assigned_datetime(frame_index: int) -> datetime:
    """Линейно распределяет отобранные кадры по календарю Aug1–Oct9 2026."""
    if SELECTED_COUNT <= 1:
        fraction = 0.0
    else:
        fraction = (frame_index - 1) / (SELECTED_COUNT - 1)
    span_days = (DEMO_PHOTOS_END - DEMO_START).days
    day_offset = fraction * span_days
    base = datetime(DEMO_START.year, DEMO_START.month, DEMO_START.day)
    result = base + timedelta(days=day_offset)
    # Разбрасываем время суток псевдослучайно, но детерминированно по номеру кадра,
    # чтобы не все фото были ровно "00:00:00".
    hour = 7 + (frame_index * 37) % 11  # 07:00-17:00 — рабочее время
    minute = (frame_index * 17) % 60
    return result.replace(hour=hour, minute=minute, second=(frame_index * 7) % 60)


def build_calendar_plan(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Календарный план"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F2937")
    extra_header_fill = PatternFill("solid", fgColor="3F4A5E")

    all_headers = [*TEMPLATE_COLUMNS, EXTRA_COLUMN_TITLE]
    for col_index, title in enumerate(all_headers, start=1):
        cell = sheet.cell(row=1, column=col_index, value=title)
        cell.font = header_font
        cell.fill = extra_header_fill if col_index > len(TEMPLATE_COLUMNS) else header_fill

    for row_number, stage in enumerate(STAGES, start=1):
        row_index = row_number + 1
        predecessor = str(row_number - 1) if row_number > 1 else ""
        values = [
            row_number,
            "",
            stage["work_name"],
            ZONE_NAME,
            stage["start"],
            stage["end"],
            None,
            predecessor,
            stage["tech"],
            _format_quantities(stage["quantities"]),
        ]
        for col_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=col_index, value=value)
            if col_index in (5, 6):
                cell.number_format = "YYYY-MM-DD"

    for col_index, title in enumerate(all_headers, start=1):
        sheet.column_dimensions[get_column_letter(col_index)].width = max(16, len(title) + 4)
    sheet.column_dimensions[get_column_letter(3)].width = 55
    sheet.column_dimensions[get_column_letter(9)].width = 55
    sheet.column_dimensions[get_column_letter(10)].width = 60

    # Итоговая сводка по всему проекту — сколько единиц каждого класса техники
    # нужно иметь в парке одновременно (максимум по этапам, а не сумма: техника
    # переходит с этапа на этап, а не покупается заново).
    # Важно: это ОТДЕЛЬНЫЙ лист, а не дополнительные строки под графиком —
    # парсер импорта читает КАЖДУЮ непустую строку после шапки как строку графика,
    # и сводка в том же листе ломала бы загрузку графика в приложении.
    peak: dict[str, int] = {}
    for stage in STAGES:
        for key, qty in stage["quantities"].items():
            peak[key] = max(peak.get(key, 0), qty)
    summary_sheet = workbook.create_sheet("Итого по технике")
    summary_sheet["A1"] = "Пиковая потребность в технике по всему графику (максимум одновременно по этапам)"
    summary_sheet["A1"].font = Font(bold=True)
    summary_sheet["A2"] = "Класс техники"
    summary_sheet["B2"] = "Кол-во, шт."
    summary_sheet["A2"].font = Font(bold=True)
    summary_sheet["B2"].font = Font(bold=True)
    for offset, (key, qty) in enumerate(peak.items(), start=3):
        summary_sheet.cell(row=offset, column=1, value=f"{CLASS_LABELS_RU[key]} ({key})")
        summary_sheet.cell(row=offset, column=2, value=qty)
    summary_sheet.column_dimensions["A"].width = 40
    summary_sheet.column_dimensions["B"].width = 12

    workbook.save(path)


def main() -> None:
    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"Не найдена папка с кадрами: {SOURCE_DIR}")

    PHOTOS_OUT.mkdir(parents=True, exist_ok=True)

    csv_rows: list[tuple[str, str]] = []
    stamped_count = 0
    for frame_index in range(1, SELECTED_COUNT + 1):
        filename = f"frame_{frame_index:06d}.jpg"
        src_path = SOURCE_DIR / filename
        if not src_path.is_file():
            print(f"пропускаю (нет файла): {filename}")
            continue

        when = assigned_datetime(frame_index)
        dst_path = PHOTOS_OUT / filename

        if frame_index <= STAMPED_FRAME_LIMIT:
            data = cv2.imdecode(np.fromfile(str(src_path), dtype="uint8"), cv2.IMREAD_COLOR)
            if data is None:
                print(f"не удалось прочитать: {filename}")
                continue
            draw_fake_timestamp(data, when)
            if not imwrite_unicode(dst_path, data):
                print(f"не удалось записать: {dst_path}")
                continue
            stamped_count += 1
        else:
            shutil.copyfile(src_path, dst_path)

        csv_rows.append((filename, when.strftime("%Y-%m-%d %H:%M:%S")))

        if frame_index % 100 == 0:
            print(f"...обработано {frame_index}/{SELECTED_COUNT}")

    csv_path = OUTPUT_ROOT / "photo_dates.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["filename", "observed_date"])
        writer.writerows(csv_rows)

    calendar_path = OUTPUT_ROOT / "calendar_plan.xlsx"
    build_calendar_plan(calendar_path)

    print(f"Готово: {len(csv_rows)} фото в {PHOTOS_OUT}")
    print(f"Из них с перерисованным штампом даты: {stamped_count}")
    print(f"Календарный план: {calendar_path}")
    print(f"Список дат фото: {csv_path}")


if __name__ == "__main__":
    main()
