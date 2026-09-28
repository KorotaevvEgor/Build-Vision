"""Сквозная проверка жизненного цикла отклонений на живом стеке.

Загружает два разных снимка в одну зону подряд и показывает, что произошло
с отклонениями: что открылось, что повторилось, что закрылось следующим
кадром. Затем печатает список отклонений и ленту событий.

Запуск:
    .venv\\Scripts\\python.exe scripts\\smoke_deviations.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
HEADERS = {"X-BuildVision-Request": "1", "Origin": "http://localhost:5173"}


def upload(session: requests.Session, project_id: int, image: Path, zone: str, camera: str, day: str) -> dict:
    with image.open("rb") as handle:
        response = session.post(
            f"{BASE}/api/projects/{project_id}/observations",
            files={"image": (image.name, handle, "image/png")},
            data={
                "zone_id": zone,
                "camera_id": camera,
                "observed_date": day,
                "date_confirmed": "true",
            },
            timeout=900,
        )
    response.raise_for_status()
    return response.json()


def run(project_id: int = 1) -> int:
    session = requests.Session()
    session.headers.update(HEADERS)
    session.post(
        f"{BASE}/api/auth/login",
        data={"username": "admin", "password": "buildvision2026"},
        timeout=30,
    )

    images = [
        Path("data/raw/images/Screenshot_10.png"),
        Path("data/raw/images/Screenshot_48.png"),
    ]
    for index, image in enumerate(images, start=1):
        if not image.exists():
            print(f"нет снимка {image}")
            return 1
        payload = upload(session, project_id, image, "zone-a", "cam-01", "2026-09-15")
        lifecycle = payload.get("deviation_lifecycle") or {}
        print(
            f"снимок {index} ({image.name}): открыто {len(lifecycle.get('opened', []))}, "
            f"повторилось {len(lifecycle.get('repeated', []))}, "
            f"закрыто автоматически {len(lifecycle.get('auto_resolved', []))}"
        )

    deviations = session.get(f"{BASE}/api/projects/{project_id}/deviations", timeout=60).json()
    print(f"\nвсего отклонений: {sum(deviations['counts'].values())} — {deviations['counts']}")
    for item in deviations["items"][:10]:
        mark = "критический путь" if item["is_on_critical_path"] else ""
        after = "есть снимок «после»" if item["after_observation_id"] else "снимка «после» нет"
        print(f"  [{item['severity']:8s}] {item['status_label_ru']:12s} {item['title'][:52]:52s} | {after} {mark}")

    events = session.get(f"{BASE}/api/projects/{project_id}/events?limit=10", timeout=60).json()
    print("\nлента событий:")
    for event in events["items"]:
        transition = f" ({event['old_value']} → {event['new_value']})" if event["new_value"] else ""
        print(f"  {event['kind_label_ru']}: {event['title'][:60]}{transition}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
