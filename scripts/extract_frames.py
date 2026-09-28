"""Нарезает видео на кадры через OpenCV с заданным интервалом (по умолчанию 1 кадр/сек).

Использование:
    python scripts/extract_frames.py <путь_к_видео> [--out <папка>] [--fps 1.0] [--probe]

--probe печатает длительность/fps/разрешение и выходит без нарезки.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2


def imwrite_unicode(path: Path, frame, quality: int = 95) -> bool:
    """cv2.imwrite молча не пишет файлы по путям с не-ASCII символами на Windows
    (кириллица в имени видео/папки) — кодируем в память и пишем сами через
    numpy.tofile(), которое корректно работает с юникодными путями."""
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return False
    buf.tofile(str(path))
    return True


def probe(path: Path) -> None:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        print(f"Не удалось открыть файл: {path}", file=sys.stderr)
        sys.exit(1)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = frame_count / fps if fps else 0
    cap.release()
    print(f"Файл: {path}")
    print(f"Разрешение: {width}x{height}")
    print(f"FPS исходного видео: {fps:.3f}")
    print(f"Кадров всего: {int(frame_count)}")
    print(f"Длительность: {duration / 60:.1f} мин ({duration:.1f} сек)")


def extract(path: Path, out_dir: Path, target_fps: float) -> int:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        print(f"Не удалось открыть файл: {path}", file=sys.stderr)
        sys.exit(1)

    source_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, round(source_fps / target_fps))

    out_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    frame_index = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if frame_index % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                out_path = out_dir / f"frame_{saved + 1:06d}.jpg"
                if imwrite_unicode(out_path, frame):
                    saved += 1
                else:
                    print(f"  не удалось записать {out_path}", file=sys.stderr)
        frame_index += 1
        if frame_index % 500 == 0:
            print(f"  ...{frame_index}/{total_frames} кадров исходного видео обработано, сохранено {saved}")

    cap.release()
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Путь к видеофайлу")
    parser.add_argument("--out", type=Path, default=None, help="Папка для кадров (по умолчанию рядом с видео)")
    parser.add_argument("--fps", type=float, default=1.0, help="Сколько кадров сохранять в секунду видео")
    parser.add_argument("--probe", action="store_true", help="Только показать метаданные видео")
    args = parser.parse_args()

    if not args.video.is_file():
        print(f"Файл не найден: {args.video}", file=sys.stderr)
        sys.exit(1)

    if args.probe:
        probe(args.video)
        return

    out_dir = args.out or args.video.with_name(args.video.stem + "_frames")
    print(f"Нарезаю {args.video} -> {out_dir} (целевая частота: {args.fps} кадр/сек)")
    saved = extract(args.video, out_dir, args.fps)
    print(f"Готово: сохранено {saved} кадров в {out_dir}")


if __name__ == "__main__":
    main()
