"""Разбор справочника видов работ в нормализованный CSV.

Источник — Excel-файл заказчика. Структура (проверена вручную):
  * Строка 2: заголовок «Справочник Видов Работ».
  * Строка 3: шапка таблицы (№ п/п, Вид работ, категории объектов).
  * С строки 4: код может быть текстом вида "12.3.1.", отсутствовать
    (тогда строка — дочерняя работа ближайшего кода выше) или быть
    датой — это Excel по ошибке превратил похожий на дату текст
    ("20.", "12" и т.п.) в datetime при исходном сохранении файла.

Испорченные коды **не реконструируются угадыванием**: настоящее
значение неизвестно, а придумывать его запрещено методикой проекта.
Такие строки помечаются `code_corrupted=true`, исходное значение
сохраняется как `code_raw_repr` для ручной проверки с заказчиком.

Результат: data/config/works_catalog.csv с колонками
  row_number, code, code_corrupted, code_raw_repr, parent_code,
  depth, work_name, categories (список через ';')

Запуск:
  python scripts/parse_works_catalog.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
SOURCE_XLSX = (
    Path.home()
    / "Downloads"
    / "7.ДГП_датасеты"
    / "Сводный перечень строительных работ_ЛТЦ.xlsx"
)
OUTPUT_CSV = ROOT / "data" / "config" / "works_catalog.csv"

HEADER_ROW = 3
FIRST_DATA_ROW = 4
CHECK_MARK = "˅"


def code_depth(code: str) -> int:
    """Число сегментов в коде вида '12.3.1.' -> 3."""
    return len([part for part in code.split(".") if part.strip()])


def main() -> None:
    if not SOURCE_XLSX.exists():
        raise SystemExit(f"Файл справочника не найден: {SOURCE_XLSX}")

    workbook = openpyxl.load_workbook(SOURCE_XLSX, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]

    header = [cell.value for cell in sheet[HEADER_ROW]]
    category_columns = [
        (index, name) for index, name in enumerate(header) if index >= 2 and name
    ]

    rows_out: list[dict] = []
    current_code: str | None = None  # последний надёжный (не испорченный) код
    corrupted_count = 0
    missing_name_count = 0

    for row_number, row in enumerate(
        sheet.iter_rows(min_row=FIRST_DATA_ROW, max_row=sheet.max_row, values_only=True),
        start=FIRST_DATA_ROW,
    ):
        raw_code = row[0]
        work_name = (row[1] or "").strip()
        if not work_name:
            missing_name_count += 1
            continue

        code_corrupted = False
        code_raw_repr = ""
        code: str | None

        if raw_code is None:
            code = None
        elif isinstance(raw_code, str):
            code = raw_code.strip()
        else:
            # datetime или число — Excel исказил исходный код; не угадываем значение.
            code_corrupted = True
            code_raw_repr = repr(raw_code)
            code = None
            corrupted_count += 1

        if code:
            current_code = code
            parent_code = None  # код есть сам по себе; иерархию выше не восстанавливаем здесь
            depth = code_depth(code)
        else:
            parent_code = current_code
            depth = code_depth(current_code) + 1 if current_code else None

        categories = [
            name
            for index, name in category_columns
            if str(row[index]).strip() == CHECK_MARK
        ]

        rows_out.append(
            {
                "row_number": row_number,
                "code": code or "",
                "code_corrupted": code_corrupted,
                "code_raw_repr": code_raw_repr,
                "parent_code": parent_code or "",
                "depth": depth if depth is not None else "",
                "work_name": work_name,
                "categories": ";".join(categories),
            }
        )

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"Строк с названием работы: {len(rows_out)}")
    print(f"Строк с испорченным кодом (не реконструированы): {corrupted_count}")
    print(f"Строк без названия работы (пропущены): {missing_name_count}")
    print(f"Категории объектов: {[name for _, name in category_columns]}")
    print(f"Результат: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
