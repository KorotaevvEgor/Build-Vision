"""Шаблон и разбор Excel-календарного плана для формы создания проекта.

См. план «Расширение страницы «Новый проект»», раздел «Структура шаблона
календарного плана». Формат — один лист, ссылки между строками идут по
видимому пользователю номеру `№`, а не по техническому slug-идентификатору,
как это принято в привычных Ганттах (MS Project, Excel-графики подрядчиков).

`TEMPLATE_COLUMNS` — единственный источник истины для порядка и названий
колонок: и генератор шаблона, и парсер обязаны использовать один и тот же
список, иначе они разойдутся при следующей правке.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
from typing import BinaryIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

#: Больше строк за одну загрузку не обрабатываем — это форма создания одного
#: проекта, а не массовый импорт нескольких объектов сразу.
MAX_ROWS = 500

TEMPLATE_COLUMNS: list[str] = [
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

#: Индексы (с 1) обязательных колонок в TEMPLATE_COLUMNS — используются только
#: для человекочитаемых сообщений об ошибках, сама проверка идёт по имени.
_REQUIRED_COLUMNS = {"№", "Наименование работ", "Зона", "Дата начала", "Дата окончания"}


@dataclass
class ParsedStageRow:
    """Одна строка листа после валидации — ссылки уже проверены, но ещё не разрешены в объекты БД."""

    row_number: int
    work_code: str
    work_name: str
    zone_name: str
    start_date: date
    end_date: date
    parent_row_number: int | None
    predecessor_row_numbers: list[int]
    technology_assumption: str


@dataclass
class ParsedSchedule:
    rows: list[ParsedStageRow] = field(default_factory=list)

    @property
    def zone_names(self) -> list[str]:
        """Уникальные имена зон в порядке первого появления в листе."""
        seen: dict[str, None] = {}
        for row in self.rows:
            seen.setdefault(row.zone_name, None)
        return list(seen)


# ---------------------------------------------------------------------------
# Генератор шаблона
# ---------------------------------------------------------------------------

#: Три работы из демонстрационного графика (data/config/demo_schedule.json),
#: показывающие обе связи — родитель (укрупнённая работа) и предшественник
#: (окончание→начало) — плюс работу второй зоны, чтобы было видно, как
#: несколько зон уживаются в одном листе.
_EXAMPLE_ROWS: list[list[object]] = [
    [
        1,
        "12.3.1.",
        "Устройство котлована",
        "Зона А",
        date(2026, 9, 10),
        date(2026, 9, 22),
        None,
        "",
        "Разработка грунта экскаватором с вывозом самосвалами — один из возможных вариантов.",
    ],
    [
        2,
        "12.3.4.",
        "Устройство фундамента",
        "Зона А",
        date(2026, 9, 23),
        date(2026, 10, 12),
        None,
        "1",
        "",
    ],
    [
        3,
        "",
        "Устройство бетонной подготовки",
        "Зона А",
        date(2026, 9, 23),
        date(2026, 9, 26),
        2,
        "1",
        "Поставка готовой бетонной смеси автобетоносмесителями — один из возможных вариантов.",
    ],
    [
        4,
        "12.7.1.",
        "Благоустройство территории",
        "Зона Б",
        date(2026, 9, 15),
        date(2026, 10, 22),
        None,
        "",
        "",
    ],
]


def build_template_workbook() -> BytesIO:
    """Генерирует `.xlsx`-шаблон с примерными строками (см. план)."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Календарный план"

    title_font = Font(bold=True, size=13)
    note_font = Font(italic=True, color="9A5B00")
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F2937")
    example_fill = PatternFill("solid", fgColor="FFF3C4")

    last_col_letter = get_column_letter(len(TEMPLATE_COLUMNS))

    sheet.merge_cells(f"A1:{last_col_letter}1")
    sheet["A1"] = "СтройКонтроль — шаблон календарного плана"
    sheet["A1"].font = title_font

    sheet.merge_cells(f"A2:{last_col_letter}2")
    sheet["A2"] = (
        "Обязательные колонки: №, Наименование работ, Зона, Дата начала, Дата окончания. "
        "Все работы одной зоны получат единую геометрию — границу площадки, нарисованную "
        "на карте на первом шаге формы; уточнить контуры зон отдельно можно позже через "
        "администратора."
    )
    sheet["A2"].font = note_font
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.row_dimensions[2].height = 30

    sheet.merge_cells(f"A3:{last_col_letter}3")
    sheet["A3"] = "Строки ниже — пример. Удалите их перед заполнением своими данными."
    sheet["A3"].font = note_font

    header_row_index = 4
    for col_index, title in enumerate(TEMPLATE_COLUMNS, start=1):
        cell = sheet.cell(row=header_row_index, column=col_index, value=title)
        cell.font = header_font
        cell.fill = header_fill

    for offset, values in enumerate(_EXAMPLE_ROWS):
        row_index = header_row_index + 1 + offset
        for col_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=col_index, value=value)
            cell.fill = example_fill
            if col_index in (5, 6):  # Дата начала / Дата окончания
                cell.number_format = "YYYY-MM-DD"

    sheet.freeze_panes = sheet.cell(row=header_row_index + 1, column=1).coordinate
    for col_index, title in enumerate(TEMPLATE_COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(col_index)].width = max(16, len(title) + 4)
    sheet.column_dimensions[get_column_letter(3)].width = 42  # Наименование работ
    sheet.column_dimensions[get_column_letter(9)].width = 50  # Технологическое допущение

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Парсер
# ---------------------------------------------------------------------------


def _find_header_row(sheet: Worksheet) -> int | None:
    """Ищет строку с заголовками шаблона среди первых строк листа.

    Строки-подсказки над шапкой (см. `build_template_workbook`) не имеют
    фиксированного числа — ищем по содержимому, а не по номеру строки.
    """
    scan_limit = min(sheet.max_row or 1, 20)
    for row in sheet.iter_rows(min_row=1, max_row=scan_limit):
        values = [_cell_str(cell.value) for cell in row[: len(TEMPLATE_COLUMNS)]]
        if values == TEMPLATE_COLUMNS:
            return row[0].row
    return None


def _cell_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_date_cell(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_int_cell(value: object) -> tuple[int | None, bool]:
    """Возвращает (число, ок). ok=False — ячейка непустая, но не число."""
    text = _cell_str(value)
    if not text:
        return None, True
    try:
        return int(float(text)), True
    except ValueError:
        return None, False


def _parse_row_number_list(value: object) -> list[int] | None:
    """Список номеров строк через запятую. Пусто → []. None → ошибка формата."""
    text = _cell_str(value)
    if not text:
        return []
    numbers: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        parsed, ok = _parse_int_cell(part)
        if not ok or parsed is None:
            return None
        numbers.append(parsed)
    return numbers


def parse_schedule_workbook(file: BinaryIO) -> ParsedSchedule | list[str]:
    """Читает и валидирует загруженный `.xlsx`.

    Возвращает разобранный график, либо (при любых ошибках) **полный** список
    сообщений — чтобы пользователь исправил всё за один проход, а не подавал
    файл заново после каждой отдельной опечатки. Поиск циклов в связях
    предшествования здесь не делается — это уже проверяет schedule_network.py
    при расчёте сети после создания проекта.
    """
    try:
        workbook = load_workbook(filename=file, data_only=True, read_only=True)
    except Exception:
        return ["Не удалось прочитать файл — убедитесь, что это корректный .xlsx"]

    sheet = workbook[workbook.sheetnames[0]]
    header_row_number = _find_header_row(sheet)
    if header_row_number is None:
        return [
            (
                "Не найдена строка заголовков шаблона — используйте кнопку «Скачать шаблон» "
                "и не переименовывайте колонки"
            )
        ]

    errors: list[str] = []
    rows: list[ParsedStageRow] = []
    seen_numbers: set[int] = set()

    data_rows = list(sheet.iter_rows(min_row=header_row_number + 1, max_row=sheet.max_row))
    if len(data_rows) > MAX_ROWS:
        errors.append(f"Слишком много строк: {len(data_rows)} (максимум {MAX_ROWS})")
        data_rows = data_rows[:MAX_ROWS]

    for excel_row in data_rows:
        cells = excel_row[: len(TEMPLATE_COLUMNS)]
        values = [cell.value for cell in cells]
        if all(v is None or _cell_str(v) == "" for v in values):
            continue  # пустая строка-разделитель — не ошибка

        record = dict(zip(TEMPLATE_COLUMNS, values, strict=False))
        row_label = f"Строка {cells[0].row}"

        row_number, number_ok = _parse_int_cell(record.get("№"))
        if not _cell_str(record.get("№")):
            errors.append(f"{row_label}: не заполнен №")
        elif not number_ok or row_number is None:
            errors.append(f"{row_label}: № должен быть целым числом")
        elif row_number in seen_numbers:
            errors.append(f"{row_label}: № {row_number} повторяется")
        if row_number is not None:
            seen_numbers.add(row_number)

        work_name = _cell_str(record.get("Наименование работ"))
        if not work_name:
            errors.append(f"{row_label}: не заполнено «Наименование работ»")

        zone_name = _cell_str(record.get("Зона"))
        if not zone_name:
            errors.append(f"{row_label}: не заполнена «Зона»")

        start_date = _parse_date_cell(record.get("Дата начала"))
        if start_date is None:
            errors.append(f"{row_label}: некорректная или пустая «Дата начала»")

        end_date = _parse_date_cell(record.get("Дата окончания"))
        if end_date is None:
            errors.append(f"{row_label}: некорректная или пустая «Дата окончания»")

        if start_date is not None and end_date is not None and end_date < start_date:
            errors.append(f"{row_label}: «Дата окончания» раньше «Даты начала»")

        parent_row_number, parent_ok = _parse_int_cell(record.get("№ родительской работы"))
        if not parent_ok:
            errors.append(f"{row_label}: «№ родительской работы» должен быть целым числом")

        predecessor_numbers = _parse_row_number_list(record.get("№ предшественников"))
        if predecessor_numbers is None:
            errors.append(f"{row_label}: «№ предшественников» — список номеров через запятую")
            predecessor_numbers = []

        if row_number is not None and work_name and zone_name and start_date and end_date:
            rows.append(
                ParsedStageRow(
                    row_number=row_number,
                    work_code=_cell_str(record.get("Код работы")),
                    work_name=work_name,
                    zone_name=zone_name,
                    start_date=start_date,
                    end_date=end_date,
                    parent_row_number=parent_row_number,
                    predecessor_row_numbers=predecessor_numbers,
                    technology_assumption=_cell_str(record.get("Технологическое допущение")),
                )
            )

    if not rows and not errors:
        errors.append("В файле нет ни одной заполненной строки")
    if errors:
        return errors

    known_numbers = {row.row_number for row in rows}
    for row in rows:
        if row.parent_row_number is not None and row.parent_row_number not in known_numbers:
            errors.append(
                f"№ {row.row_number}: родительская работа № {row.parent_row_number} "
                "не найдена в листе"
            )
        for predecessor in row.predecessor_row_numbers:
            if predecessor not in known_numbers:
                errors.append(f"№ {row.row_number}: предшественник № {predecessor} не найден в листе")

    if errors:
        return errors

    return ParsedSchedule(rows=rows)
