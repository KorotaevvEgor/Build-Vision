"""Разовая проверка интеграции backend/app с Django ORM/PostgreSQL.

Не часть постоянного набора тестов — запускается вручную внутри контейнера
с доступом к Postgres (см. README, раздел проверки), поскольку на машине
разработки прямое подключение Windows -> forwarded-порт Postgres не
работает (см. docs/PROJECT_DOCUMENTATION.md, известное ограничение среды).

Проверяет:
  1. load_schedule()/load_equipment_rules()/load_vocabulary()/
     load_weather_rules() реально читают из БД, а не из файлов
     (файлы временно переименовываются, чтобы файловый откат гарантированно
     провалился, если код всё же попробует его использовать).
  2. persistence.persist_observation() пишет Observation/Detection/
     StageEvaluationRecord, persistence.get_observation() читает их обратно.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, "/app/backend")

from app import django_bridge
from app.config import (
    DEMO_SCHEDULE_PATH,
    DEMO_SITE_GEOJSON_PATH,
    EQUIPMENT_RULES_PATH,
    VOCABULARY_PATH,
    WEATHER_RULES_PATH,
)
from app.detector import Detection
from app.matching import evaluate_observation
from app.persistence import get_observation, persist_observation
from app.rules_config import load_equipment_rules
from app.schedule import load_schedule
from app.vocabulary import load_vocabulary
from app.weather_rules_config import load_weather_rules

CONFIG_FILES = [
    VOCABULARY_PATH,
    EQUIPMENT_RULES_PATH,
    DEMO_SCHEDULE_PATH,
    DEMO_SITE_GEOJSON_PATH,
    WEATHER_RULES_PATH,
]


def main() -> None:
    assert django_bridge.ensure_django_ready(), "БД должна быть доступна для этой проверки"

    renamed: list[tuple[Path, Path]] = []
    for path in CONFIG_FILES:
        moved = path.with_suffix(path.suffix + ".disabled")
        path.rename(moved)
        renamed.append((path, moved))

    try:
        vocabulary = load_vocabulary()
        assert vocabulary.classes, "Словарь классов пуст — DB-путь не сработал"
        print(f"[OK] load_vocabulary(): {len(vocabulary.classes)} классов из БД")

        rules = load_equipment_rules()
        assert "stage-kotlovan" in rules.stage_rules, "Правило stage-kotlovan не найдено в БД"
        print(f"[OK] load_equipment_rules(): {len(rules.stage_rules)} правил из БД")

        schedule = load_schedule()
        assert schedule.stages, "График пуст — DB-путь не сработал"
        print(f"[OK] load_schedule(): {len(schedule.stages)} этапов из БД")

        weather_rules = load_weather_rules()
        assert weather_rules, "Погодные правила пусты — DB-путь не сработал"
        print(f"[OK] load_weather_rules(): {len(weather_rules)} правил из БД")

        detections = [
            Detection(
                class_key="excavator",
                label_ru="Экскаватор",
                in_taxonomy=True,
                confidence=0.91,
                bbox=[10.0, 20.0, 100.0, 150.0],
                ambiguous=False,
                runner_up_class_key=None,
                runner_up_confidence=None,
            ),
            Detection(
                class_key="dump_truck",
                label_ru="Самосвал",
                in_taxonomy=True,
                confidence=0.72,
                bbox=[200.0, 60.0, 320.0, 180.0],
                ambiguous=False,
                runner_up_class_key=None,
                runner_up_confidence=None,
            ),
        ]
        evaluation = evaluate_observation(
            zone_id="zone-a",
            observed_date=date(2026, 9, 15),
            date_confirmed=True,
            detections=detections,
            schedule=schedule,
            rules=rules,
        )
        assert evaluation.overall_status == "no_deviation", evaluation.overall_status

        observation_id = uuid.uuid4()
        saved = persist_observation(
            observation_id=observation_id,
            zone_id="zone-a",
            image_path="/tmp/verify.png",
            image_sha256="0" * 64,
            evaluation=evaluation,
        )
        assert saved, "persist_observation() вернул False"
        print(f"[OK] persist_observation(): сохранено {observation_id}")

        fetched = get_observation(str(observation_id))
        assert fetched is not None, "get_observation() не нашёл только что сохранённую запись"
        assert fetched["overall_status"] == "no_deviation"
        assert len(fetched["detections"]) == 2
        assert len(fetched["stages"]) == 1
        print("[OK] get_observation(): запись читается обратно с теми же данными")

        print("\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ.")
    finally:
        for original, moved in renamed:
            moved.rename(original)


if __name__ == "__main__":
    main()
