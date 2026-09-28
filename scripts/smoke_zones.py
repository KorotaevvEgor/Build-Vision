"""Сквозная проверка зон кадра, определения простоя и зональных отклонений.

Один и тот же снимок загружается дважды подряд. Это моделирует реальную
ситуацию: камера снимает раз в полчаса, техника с места не сдвинулась.
На втором прогоне система обязана увидеть историю кадров и признать простой.

Запуск:
    .venv\\Scripts\\python.exe scripts\\smoke_zones.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
LOGIN = {"username": "admin", "password": "buildvision2026"}
HEADERS = {"X-BuildVision-Request": "1", "Origin": "http://localhost:5173"}


def run(image_path: Path, zone_id: str, camera_id: str, observed_date: str) -> int:
    session = requests.Session()
    session.headers.update(HEADERS)
    session.post(f"{BASE}/api/auth/login", data=LOGIN, timeout=30)

    for attempt in (1, 2):
        with image_path.open("rb") as handle:
            response = session.post(
                f"{BASE}/api/observations",
                files={"image": (image_path.name, handle, "image/png")},
                data={
                    "zone_id": zone_id,
                    "camera_id": camera_id,
                    "observed_date": observed_date,
                    "date_confirmed": "true",
                },
                timeout=900,
            )
        print(f"\n=== прогон {attempt}: HTTP {response.status_code} ===")
        if response.status_code != 200:
            print(response.text[:500])
            return 1

        payload = response.json()
        detections = [d for d in payload.get("detections", []) if d.get("in_taxonomy")]
        print(f"детекций в таксономии: {len(detections)}")
        for detection in detections[:8]:
            zone = detection.get("frame_zone_name") or "вне зон"
            reason = (detection.get("activity_reason") or "")[:70]
            print(f"  {detection['label_ru']:22s} | {zone:18s} | {detection['activity']:8s} | {reason}")

        findings = (payload.get("ai") or {}).get("zone_deviations", [])
        if findings:
            print("отклонения по зонам:")
            for item in findings:
                print(f"  [{item['severity']}] {item['title']}: {item['message'][:130]}")
        else:
            print("отклонений по зонам не выявлено")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw/images/Screenshot_10.png")
    raise SystemExit(run(target, "zone-a", "cam-01", "2026-09-15"))
