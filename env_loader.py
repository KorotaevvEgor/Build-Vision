"""Загрузка переменных окружения из .env в корне репозитория.

В Docker переменные приходят из docker-compose, и файла .env там нет —
загрузчик просто ничего не делает. Локально он избавляет от необходимости
выставлять DATABASE_URL и ключи вручную в каждой консоли.

Уже выставленные переменные окружения имеют приоритет над файлом:
это позволяет переопределить любое значение из командной строки.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_env(path: Path = ENV_PATH) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env()
