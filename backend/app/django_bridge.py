"""Инициализация Django ORM внутри процесса FastAPI.

Модели и админка живут в корне репозитория (admin_panel/, core/) —
единый источник правды для конфигурации (словарь классов, правила,
график, зоны) и истории анализа (Observation/Detection/...). FastAPI
не поднимает Django-приложение целиком, а использует только ORM для
чтения/записи в ту же PostgreSQL, что видна через Django admin.

Если БД временно недоступна (например, при локальной разработке без
поднятого Postgres), `ensure_django_ready()` возвращает False, и
вызывающий код должен откатиться на файловый источник конфигурации —
см. schedule.py/rules_config.py/vocabulary.py/weather_rules_config.py.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_setup_lock = threading.Lock()
_setup_done = False


def _run_django_setup() -> None:
    global _setup_done
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin_panel.settings")

    import django

    django.setup()
    _setup_done = True


def ensure_django_ready() -> bool:
    """Готовит Django ORM и проверяет реальную доступность БД.

    Возвращает True, только если можно действительно выполнять запросы —
    настроенный, но недоступный Postgres не должен маскироваться под
    "готово".
    """
    with _setup_lock:
        if not _setup_done:
            try:
                _run_django_setup()
            except Exception:
                logger.exception("Не удалось инициализировать Django ORM")
                return False

    from django.db import connections
    from django.db.utils import OperationalError

    try:
        connections["default"].ensure_connection()
        return True
    except OperationalError:
        logger.warning(
            "PostgreSQL недоступен — используется резервная файловая конфигурация "
            "из data/config/. Изменения через Django admin не будут видны, пока БД "
            "не станет доступна."
        )
        return False
