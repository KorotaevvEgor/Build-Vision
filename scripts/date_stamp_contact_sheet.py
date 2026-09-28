"""Контактный лист нижних полос всех снимков — проверить, на скольких есть штамп даты.

Штамп даты (если есть) обычно лежит в правом или левом нижнем углу.
Вырезаем нижнюю полосу каждого кадра, подписываем именем файла и
собираем в один лист для быстрого визуального аудита без открытия
ста отдельных файлов.

Запуск:
  python scripts/date_stamp_contact_sheet.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
IMAGES_DIR = ROOT / "data" / "raw" / "images"
OUTPUT_DIR = ROOT / "data" / "interim"

STRIP_HEIGHT = 110
COLUMNS = 2
LABEL_HEIGHT = 18
BATCH_SIZE = 10  # по 10 листов по 10 снимков — цифры даты должны оставаться читаемыми


def natural_key(name: str) -> tuple[str, int]:
    stem = Path(name).stem
    head, _, tail = stem.rpartition("_")
    return (head, int(tail)) if tail.isdigit() else (stem, 0)


def load_font(size: int = 12) -> ImageFont.ImageFont:
    for candidate in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def main() -> None:
    paths = sorted(IMAGES_DIR.glob("*.png"), key=lambda p: natural_key(p.name))
    font = load_font()

    strips: list[Image.Image] = []
    for path in paths:
        with Image.open(path) as image:
            width, height = image.size
            crop = image.convert("RGB").crop((0, height - STRIP_HEIGHT, width, height))
        canvas = Image.new("RGB", (width, STRIP_HEIGHT + LABEL_HEIGHT), (30, 30, 30))
        canvas.paste(crop, (0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.text((4, STRIP_HEIGHT + 1), path.stem, fill=(255, 255, 255), font=font)
        strips.append(canvas)

    cell_w = max(s.width for s in strips)
    cell_h = max(s.height for s in strips)

    # Держим размер близким к оригиналу: цифры штампа мелкие, сильное уменьшение делает их нечитаемыми.
    scale = min(1.0, 620 / cell_w)
    thumb_w, thumb_h = int(cell_w * scale), int(cell_h * scale)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    batches = [strips[i : i + BATCH_SIZE] for i in range(0, len(strips), BATCH_SIZE)]
    for batch_index, batch in enumerate(batches, start=1):
        rows = (len(batch) + COLUMNS - 1) // COLUMNS
        sheet = Image.new("RGB", (thumb_w * COLUMNS, thumb_h * rows), (10, 10, 10))
        for index, strip in enumerate(batch):
            thumb = strip.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
            col, row = index % COLUMNS, index // COLUMNS
            sheet.paste(thumb, (col * thumb_w, row * thumb_h))
        output_path = OUTPUT_DIR / f"date_stamp_contact_sheet_{batch_index}.jpg"
        sheet.save(output_path, quality=80)
        print(f"Лист {batch_index}: {output_path} ({sheet.width}x{sheet.height})")

    print(f"Снимков всего: {len(strips)}")


if __name__ == "__main__":
    main()
