"""Проверка кривой готовности объектов.

Запуск:
    .venv\\Scripts\\python.exe scripts\\smoke_readiness.py
"""

from __future__ import annotations

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

    projects = session.get(f"{BASE}/api/projects", timeout=60).json()["projects"]
    for project in projects:
        project_id = project["project_id"]
        response = session.get(f"{BASE}/api/projects/{project_id}/readiness", timeout=120)
        if response.status_code != 200:
            print(f"{project['name']}: HTTP {response.status_code}")
            continue

        payload = response.json()
        if not payload["available"]:
            print(f"{project['name']}: оценок готовности нет")
            continue

        points = " ".join(
            f"{item['date'][5:]}→{item['readiness_percent']}%" for item in payload["fact"]
        )
        print(f"{project['name']}")
        print(f"   кривая: {points}")
        print(
            f"   плановых работ: {len(payload['planned_stages'])}, "
            f"сейчас по графику: {payload['current_planned_work'] or '—'}"
        )
        if payload["mismatch"]:
            print(f"   вердикт: {payload['mismatch']['message']}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
