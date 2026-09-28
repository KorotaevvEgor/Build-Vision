"""Демонстрационная временная история наблюдений.

Заполняет графики на Главной/в Аналитике, которые иначе были бы пустыми
сразу после деплоя. Прогоняет РЕАЛЬНЫЙ детектор на нескольких снимках
датасета для каждой зоны — тем же кодом, что и `POST /api/observations`
(`evaluate_observation` + `persist_observation`), никаких выдуманных
результатов детекции. Единственное, что здесь синтетическое, — метка
времени: после сохранения `created_at` переносится на последние
`HISTORY_DAYS` дней, чтобы история не была сосредоточена в один момент
запуска скрипта.

Не часть постоянного набора тестов — запускается вручную один раз после
деплоя, внутри контейнера с доступом к Postgres (см. README):

  docker compose exec app python /app/scripts/seed_demo_history.py
"""

from __future__ import annotations

import hashlib
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, "/app/backend")

from app import django_bridge
from app.detector import get_detector
from app.matching import evaluate_observation
from app.persistence import persist_observation
from app.rules_config import load_equipment_rules
from app.schedule import load_schedule

IMAGES_DIR = Path("/app/data/raw/images")
IMAGES_PER_ZONE = 6
HISTORY_DAYS = 7
SEED = 42


def _pick_images(count: int) -> list[Path]:
    images = sorted(IMAGES_DIR.glob("*.png"))
    if not images:
        raise SystemExit(f"Нет снимков в {IMAGES_DIR} — проверьте, что образ собран с data/raw/images")
    random.Random(SEED).shuffle(images)
    return images[:count]


def _sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def main() -> None:
    if not django_bridge.ensure_django_ready():
        raise SystemExit("БД недоступна — этот скрипт запускается только там, где есть доступ к Postgres")

    from core.models import Observation

    schedule = load_schedule()
    rules = load_equipment_rules()
    zone_ids = sorted({s.zone_id for s in schedule.stages})
    if not zone_ids:
        raise SystemExit("В графике нет ни одной зоны — нечего заполнять")

    images = iter(_pick_images(IMAGES_PER_ZONE * len(zone_ids)))
    detector = get_detector()
    created_ids: list[uuid.UUID] = []

    for zone_id in zone_ids:
        stages_for_zone = [s for s in schedule.stages if s.zone_id == zone_id]
        if not stages_for_zone:
            continue
        for _ in range(IMAGES_PER_ZONE):
            image_path = next(images, None)
            if image_path is None:
                break

            # Наблюдаемая дата — случайный день внутри периода одного из этапов
            # зоны, чтобы на каждом снимке был активный этап и осмысленный результат.
            stage = random.choice(stages_for_zone)
            span_days = max((stage.end_date - stage.start_date).days, 0)
            observed_date = stage.start_date + timedelta(days=random.randint(0, span_days))

            detections = detector.detect(image_path)
            evaluation = evaluate_observation(
                zone_id=zone_id,
                observed_date=observed_date,
                date_confirmed=True,
                detections=detections,
                schedule=schedule,
                rules=rules,
            )
            observation_id = uuid.uuid4()
            saved = persist_observation(
                observation_id=observation_id,
                zone_id=zone_id,
                image_path=str(image_path),
                image_sha256=_sha256_of(image_path),
                evaluation=evaluation,
            )
            if saved:
                created_ids.append(observation_id)
                print(f"[OK] {zone_id}: {image_path.name} -> {evaluation.overall_status}")
            else:
                print(f"[WARN] {zone_id}: {image_path.name} — не удалось сохранить в БД")

    now = datetime.now(UTC)
    for observation_id in created_ids:
        offset_seconds = random.uniform(0, HISTORY_DAYS * 24 * 60 * 60)
        Observation.objects.filter(id=observation_id).update(created_at=now - timedelta(seconds=offset_seconds))

    print(
        f"\nГотово: {len(created_ids)} демонстрационных наблюдений добавлено "
        f"(реальные детекции модели, синтетически распределённая временная шкала "
        f"за последние {HISTORY_DAYS} дней)."
    )


if __name__ == "__main__":
    random.seed(SEED)
    main()
