"""Тесты для backend/app/learning.py и связанных эндпоинтов main.py.

Файл проверяет две разные вещи, и их важно не смешивать:

1. Честная деградация при недоступной БД: функции обязаны возвращать
   `available: False`/`None`/явную причину отказа, а не выдуманные данные.
   Недоступность задаётся явно фикстурой `database_unavailable` — раньше она
   подразумевалась из окружения, и тесты молча меняли смысл и падали, как
   только на машине появлялась рабочая база.
2. Поведение HTTP-эндпоинтов на рабочей БД: коды ответов при некорректном
   запросе и при отсутствующем объекте. Здесь БД нужна: маршруты закрыты
   зависимостью, которая при недоступной базе честно отдаёт 503.
"""

from __future__ import annotations

import pytest
from app import auth, django_bridge, learning
from app.main import app
from fastapi.testclient import TestClient

app.dependency_overrides[auth.get_current_user] = lambda: auth.CurrentUser(
    id=1,
    username="test-admin",
    full_name="Тестовый администратор",
    role="admin",
    role_label="Администратор",
    position="",
    display_position="Администратор",
)

client = TestClient(app, headers={"X-BuildVision-Request": "1"})


@pytest.fixture
def database_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Моделирует недоступную БД.

    Патчится атрибут модуля, а не импортированная функция: `learning.py`
    вызывает `django_bridge.ensure_django_ready()` по имени модуля, поэтому
    подмена действует и на прямые вызовы, и на вызовы из эндпоинтов.
    """
    monkeypatch.setattr(django_bridge, "ensure_django_ready", lambda: False)


# --- Честная деградация при недоступной БД ---------------------------------


def test_save_correction_returns_none_without_db(database_unavailable: None) -> None:
    result = learning.save_correction(
        observation_id="00000000-0000-0000-0000-000000000000",
        bbox=[0, 0, 10, 10],
        original_class_key="excavator",
        original_confidence=0.5,
        corrected_class_key="excavator",
        user_id=1,
    )
    assert result is None


def test_learning_stats_reports_unavailable_without_db(database_unavailable: None) -> None:
    assert learning.learning_stats() == {"available": False}


def test_list_model_versions_reports_unavailable_without_db(database_unavailable: None) -> None:
    assert learning.list_model_versions() == {"available": False, "versions": []}


def test_count_available_corrections_is_zero_without_db(database_unavailable: None) -> None:
    assert learning.count_available_corrections() == 0


def test_trigger_training_refuses_without_corrections(database_unavailable: None) -> None:
    result = learning.trigger_training()
    assert result["started"] is False
    assert "коррекции" in result["reason"]


def test_deploy_version_returns_none_without_db(database_unavailable: None) -> None:
    assert learning.deploy_version(1) is None


def test_stats_endpoint_reports_unavailable_without_db(database_unavailable: None) -> None:
    response = client.get("/api/learning/stats")
    assert response.status_code == 200
    assert response.json() == {"available": False}


def test_model_versions_endpoint_reports_unavailable_without_db(
    database_unavailable: None,
) -> None:
    response = client.get("/api/model-versions")
    assert response.status_code == 200
    assert response.json() == {"available": False, "versions": []}


# --- Поведение эндпоинтов на рабочей БД ------------------------------------


def test_create_correction_endpoint_rejects_invalid_bbox() -> None:
    response = client.post(
        "/api/corrections",
        json={
            "observation_id": "00000000-0000-0000-0000-000000000000",
            "bbox": [0, 0, 10],
            "original_class_key": "excavator",
            "corrected_class_key": "excavator",
        },
    )
    assert response.status_code == 400


def test_create_correction_endpoint_404_when_observation_missing() -> None:
    response = client.post(
        "/api/corrections",
        json={
            "observation_id": "00000000-0000-0000-0000-000000000000",
            "bbox": [0, 0, 10, 10],
            "original_class_key": "excavator",
            "corrected_class_key": "excavator",
        },
    )
    assert response.status_code == 404


def test_learning_stats_endpoint_returns_known_shape() -> None:
    """На рабочей БД проверяется форма ответа, а не конкретные счётчики.

    Числа зависят от накопленных коррекций и меняются в ходе работы —
    прибивать их в тесте значило бы проверять состояние, а не контракт.
    """
    response = client.get("/api/learning/stats")
    assert response.status_code == 200
    body = response.json()
    assert "available" in body
    if body["available"]:
        for key in ("correction_count", "confirmation_count", "fixed_error_count"):
            assert isinstance(body[key], int)


def test_model_versions_endpoint_returns_known_shape() -> None:
    response = client.get("/api/model-versions")
    assert response.status_code == 200
    body = response.json()
    assert "available" in body
    assert isinstance(body.get("versions", []), list)


def test_train_model_version_endpoint_refuses_without_corrections() -> None:
    response = client.post("/api/model-versions/train")
    assert response.status_code == 200
    body = response.json()
    assert body["started"] is False


def test_deploy_model_version_endpoint_404_when_missing() -> None:
    response = client.post("/api/model-versions/999/deploy")
    assert response.status_code == 404
