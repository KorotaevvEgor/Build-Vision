"""Проверка экрана участка надзора и очереди разбора.

Запуск:
    .venv\\Scripts\\python.exe scripts\\smoke_supervision.py
"""

from __future__ import annotations

import json

import requests

BASE = "http://127.0.0.1:8000"
HEADERS = {"X-BuildVision-Request": "1", "Origin": "http://localhost:5173"}


def run() -> int:
    session = requests.Session()
    session.headers.update(HEADERS)
    session.post(
        f"{BASE}/api/auth/login",
        data={"username": "admin", "password": "buildvision2026"},
        timeout=30,
    )

    response = session.get(f"{BASE}/api/supervision", timeout=180)
    print(f"HTTP {response.status_code}")
    if response.status_code != 200:
        print(response.text[:600])
        return 1

    payload = response.json()
    print("итоги:", json.dumps(payload["totals"], ensure_ascii=False))
    print()
    for item in payload["objects"]:
        readiness = f"{item['readiness_percent']}%" if item["readiness_percent"] is not None else "—"
        days = item["days_since_last_observation"]
        print(
            f"  {item['name'][:30]:30s} {item['schedule_status_label_ru'][:22]:22s} "
            f"сдвиг {item['shift_days']:4d}  готовность {readiness:>5s}  "
            f"отклонений {item['open_deviations']}  последний снимок {days if days is not None else '—'} дн."
        )

    print("\nвне контроля:", ", ".join(x["name"] for x in payload["stale_objects"]) or "нет")

    queue = session.get(f"{BASE}/api/supervision/queue", timeout=180).json()
    print(f"\nочередь разбора: {queue['total']}")
    for item in queue["items"]:
        mark = "КП" if item["is_on_critical_path"] else "  "
        print(
            f"  {mark} [{item['severity']:8s}] {item['project_name'][:26]:26s} "
            f"{item['title'][:46]}  (подтверждений: {item['occurrence_count']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
