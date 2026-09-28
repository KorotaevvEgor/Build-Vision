"""Первый сквозной сценарий: снимок -> детекция -> правила -> объяснение.

Использует настоящую модель (медленно, ~секунды на CPU) и настоящий снимок
из датасета — сознательно не мокаем детектор, чтобы проверить весь путь
целиком, как того требует план (раздел «Проверка качества и готовности»).
"""

from __future__ import annotations

from pathlib import Path

from app import auth
from app.main import app
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_IMAGE = ROOT / "data" / "raw" / "images" / "Screenshot_48.png"

# Авторизация требует живой БД (сессии хранятся в django_session) — эти тесты проверяют
# детектор/движок сопоставления на файловом откате без Живой БД (см. django_bridge.py) —
# поэтому зависимость авторизации переопределена стандартным для FastAPI способом —
# отдельно от проверки самой авторизации (она покрыта отдельно в test_auth.py).
app.dependency_overrides[auth.get_current_user] = lambda: auth.CurrentUser(
    id=1,
    username="test-admin",
    full_name="Тестовый пользователь",
    role="admin",
    role_label="Администратор",
    position="",
    display_position="Администратор",
)

client = TestClient(app, headers={"X-BuildVision-Request": "1"})


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_site_and_zones_are_served() -> None:
    response = client.get("/api/site")
    assert response.status_code == 200
    body = response.json()
    assert body["schedule_is_demo"] is True
    zone_ids = {stage["zone_id"] for stage in body["stages"]}
    assert {"zone-a", "zone-b"} <= zone_ids


def test_observation_without_confirmed_date_is_insufficient_data() -> None:
    assert SAMPLE_IMAGE.exists(), f"Нет тестового снимка: {SAMPLE_IMAGE}"
    with SAMPLE_IMAGE.open("rb") as handle:
        response = client.post(
            "/api/observations",
            data={"zone_id": "zone-a", "date_confirmed": "false"},
            files={"image": ("Screenshot_48.png", handle, "image/png")},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "insufficient_data"
    assert body["date_confirmed"] is False
    # Детектор всё равно должен был отработать и вернуть сырые детекции.
    assert isinstance(body["detections"], list)


def test_observation_with_confirmed_date_runs_full_pipeline() -> None:
    assert SAMPLE_IMAGE.exists(), f"Нет тестового снимка: {SAMPLE_IMAGE}"
    with SAMPLE_IMAGE.open("rb") as handle:
        response = client.post(
            "/api/observations",
            data={
                "zone_id": "zone-a",
                "observed_date": "2026-09-15",  # внутри stage-kotlovan (10–22 сентября)
                "date_confirmed": "true",
            },
            files={"image": ("Screenshot_48.png", handle, "image/png")},
        )
    assert response.status_code == 200
    body = response.json()

    assert body["date_confirmed"] is True
    assert body["overall_status"] in {"no_deviation", "possible_deviation", "insufficient_data"}
    assert len(body["stages"]) == 1
    stage = body["stages"][0]
    assert stage["stage_id"] == "stage-kotlovan"
    assert set(stage["required"]) == {"excavator", "dump_truck"}
    # Объяснение должно быть непустым и на русском — того требует методика.
    assert stage["explanation_ru"]
    assert isinstance(body["detections"], list) and len(body["detections"]) > 0


def test_unknown_zone_is_rejected() -> None:
    with SAMPLE_IMAGE.open("rb") as handle:
        response = client.post(
            "/api/observations",
            data={"zone_id": "zone-does-not-exist", "date_confirmed": "false"},
            files={"image": ("Screenshot_48.png", handle, "image/png")},
        )
    assert response.status_code == 404
