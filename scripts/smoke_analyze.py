"""Сквозная проверка локального стека: вход, зоны площадки, анализ снимка.

Запуск:
    .venv\\Scripts\\python.exe scripts\\smoke_analyze.py <путь-к-снимку> [ГГГГ-ММ-ДД]

Проверяет то, что увидит пользователь: авторизацию по сессии Django,
доступность зон графика и полный цикл анализа изображения.
Без подтверждённой даты съёмки ядро сопоставления по замыслу отвечает
«Недостаточно данных», поэтому дату можно передать вторым аргументом.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
LOGIN = {"username": "admin", "password": "buildvision2026"}
HEADERS = {"X-BuildVision-Request": "1", "Origin": "http://localhost:5173"}


def main(image_path: Path, observed_date: str | None) -> int:
    if not image_path.is_file():
        print("файл не найден:", image_path)
        return 1

    session = requests.Session()
    session.headers.update(HEADERS)

    response = session.post(f"{BASE}/api/auth/login", data=LOGIN, timeout=30)
    print("вход:", response.status_code, response.json().get("user", {}).get("username"))
    if response.status_code != 200:
        return 1

    site = session.get(f"{BASE}/api/site", timeout=30).json()
    zones = [
        feature["properties"]
        for feature in site.get("geojson", {}).get("features", [])
        if feature.get("properties", {}).get("kind") == "zone"
    ]
    print("зон на площадке:", len(zones), [z["id"] for z in zones])
    print("этапов графика:", len(site.get("stages", [])))
    for stage in site.get("stages", []):
        print(f"  {stage['zone_id']:10s} {stage['start_date']}..{stage['end_date']}  {stage['work_name']}")
    if not zones:
        return 1

    zone_id = zones[0]["id"]
    payload = {"zone_id": zone_id}
    if observed_date:
        payload["observed_date"] = observed_date
        payload["date_confirmed"] = "true"

    started = time.monotonic()
    with image_path.open("rb") as handle:
        result = session.post(
            f"{BASE}/api/observations",
            files={"image": (image_path.name, handle, "image/png")},
            data=payload,
            timeout=900,
        )
    elapsed = time.monotonic() - started
    print(f"\nанализ снимка: HTTP {result.status_code} за {elapsed:.1f} с (зона {zone_id})")

    if result.status_code != 200:
        print(result.text[:1000])
        return 1

    data = result.json()
    print("сохранено в БД:", data.get("saved_to_db"))
    print("статус:", data.get("overall_status_label_ru"))
    print("объяснение:", str(data.get("overall_explanation_ru"))[:400])

    detections = data.get("detections", [])
    print("детекций:", len(detections))
    for detection in detections[:15]:
        mark = " (неоднозначно)" if detection.get("ambiguous") else ""
        print(f"  {detection.get('label_ru'):28s} {detection.get('confidence'):.2f}{mark}")

    runs_dir = Path("data/runs")
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "smoke_last.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("полный ответ: data/runs/smoke_last.json")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw/images/Screenshot_12.png")
    when = sys.argv[2] if len(sys.argv) > 2 else None
    raise SystemExit(main(target, when))
