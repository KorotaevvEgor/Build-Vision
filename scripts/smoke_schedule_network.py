"""Проверка сетевого графика: критический путь, запас и сдвиг даты сдачи.

Запуск:
    .venv\\Scripts\\python.exe scripts\\smoke_schedule_network.py
"""

from __future__ import annotations

import requests

BASE = "http://127.0.0.1:8000"
HEADERS = {"X-BuildVision-Request": "1", "Origin": "http://localhost:5173"}


def run(project_id: int = 1) -> int:
    session = requests.Session()
    session.headers.update(HEADERS)
    session.post(
        f"{BASE}/api/auth/login",
        data={"username": "admin", "password": "buildvision2026"},
        timeout=30,
    )

    response = session.get(f"{BASE}/api/projects/{project_id}/schedule-network", timeout=60)
    print(f"HTTP {response.status_code}")
    if response.status_code != 200:
        print(response.text[:600])
        return 1

    payload = response.json()
    print(
        f"{payload['status_label_ru']}: план {payload['baseline_finish_date']}, "
        f"прогноз {payload['projected_finish_date']}, сдвиг {payload['shift_days']} дн."
    )
    print(f"критический путь: {', '.join(payload['critical_stage_ids'])}")
    if payload["unverified_stage_ids"]:
        print(f"без подтверждения: {', '.join(payload['unverified_stage_ids'])}")

    print(f"{'работа':44s} | ур | зап | крит | состояние")
    for stage in payload["stages"]:
        name = ("  " * stage["level"]) + stage["work_name"]
        print(
            f"{name[:44]:44s} | {stage['level']:2d} | {stage['total_float_days']:3d} | "
            f"{'да' if stage['is_critical'] else '  '}   | {stage['state_label_ru']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
