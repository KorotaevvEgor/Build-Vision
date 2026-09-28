"""Проверка проектного эндпоинта наблюдений: зоны кадра и активность в ответе.

Легаси-маршрут /api/observations уже отдавал эти поля, проектный — нет.
Скрипт подтверждает, что оба ответа теперь одинаковы по составу.

Запуск:
    .venv\\Scripts\\python.exe scripts\\smoke_project_zones.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
HEADERS = {"X-BuildVision-Request": "1", "Origin": "http://localhost:5173"}


def run(image_path: Path, project_id: int, zone_id: str, camera_id: str) -> int:
    session = requests.Session()
    session.headers.update(HEADERS)
    session.post(
        f"{BASE}/api/auth/login",
        data={"username": "admin", "password": "buildvision2026"},
        timeout=30,
    )

    with image_path.open("rb") as handle:
        response = session.post(
            f"{BASE}/api/projects/{project_id}/observations",
            files={"image": (image_path.name, handle, "image/png")},
            data={
                "zone_id": zone_id,
                "camera_id": camera_id,
                "observed_date": "2026-09-15",
                "date_confirmed": "true",
            },
            timeout=900,
        )

    print(f"HTTP {response.status_code}")
    if response.status_code != 200:
        print(response.text[:500])
        return 1

    payload = response.json()
    for detection in payload.get("detections", []):
        if not detection.get("in_taxonomy"):
            continue
        zone = detection.get("frame_zone_name") or "вне зон"
        reason = (detection.get("activity_reason") or "")[:60]
        print(f"  {detection['label_ru']:22s} | {zone:18s} | {detection.get('activity')} | {reason}")

    findings = (payload.get("ai") or {}).get("zone_deviations", [])
    for item in findings:
        print(f"  [{item['severity']}] {item['title']}")
    if not findings:
        print("  отклонений по зонам не выявлено")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw/images/Screenshot_10.png")
    raise SystemExit(run(target, 1, "zone-a", "cam-01"))
