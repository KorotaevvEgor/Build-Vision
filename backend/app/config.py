"""Пути к данным и конфигурации. Один источник правды для всего backend."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Локальные переменные окружения из .env в корне репозитория (в Docker файла нет).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import env_loader  # noqa: F401  (импорт ради побочного эффекта загрузки .env)

DATA_DIR = ROOT / "data"
CONFIG_DIR = DATA_DIR / "config"

VOCABULARY_PATH = CONFIG_DIR / "vocabulary.yaml"
EQUIPMENT_RULES_PATH = CONFIG_DIR / "equipment_rules.yaml"
WEATHER_RULES_PATH = CONFIG_DIR / "weather_rules.yaml"
WORKS_CATALOG_PATH = CONFIG_DIR / "works_catalog.csv"
DEMO_SCHEDULE_PATH = CONFIG_DIR / "demo_schedule.json"
DEMO_SITE_GEOJSON_PATH = CONFIG_DIR / "demo_site.geojson"

MODELS_DIR = ROOT / "models"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "app.db"

# Символьная метка для коррекций типа «это не техника» (Correction.corrected_class=None) —
# общая для скрипта обучения (scripts/train_correction_classifier.py) и детектора (detector.py).
CORRECTION_NOT_EQUIPMENT_LABEL = "__not_equipment__"

DEFAULT_MODEL_WEIGHTS = os.environ.get("SK_MODEL_WEIGHTS", "yolov8s-worldv2.pt")
DEFAULT_IMGSZ = int(os.environ.get("SK_IMGSZ", "960"))
DEFAULT_CONF = float(os.environ.get("SK_CONF", "0.25"))
DEFAULT_IOU = float(os.environ.get("SK_IOU", "0.50"))
DEFAULT_MAX_DET = int(os.environ.get("SK_MAX_DET", "60"))

# Кэши ultralytics/torch — вне системного диска на машине разработки (задаётся через окружение, не здесь жёстко).
for _env_name, _sk_name in (("YOLO_CONFIG_DIR", "SK_YOLO_CONFIG_DIR"), ("TORCH_HOME", "SK_TORCH_HOME")):
    _value = os.environ.get(_sk_name)
    if _value:
        os.environ.setdefault(_env_name, _value)
