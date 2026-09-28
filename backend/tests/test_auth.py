"""Юнит-тесты для backend/app/auth.py, не требующие живой БД.

Сессии/пароли проверяются через django.contrib.auth и django.contrib.sessions
(см. auth.py) — это требует настоящего Postgres, которого нет в этом окружении
(см. django_bridge.py). Здесь проверяется только независимая от БД логика:
разграничение ролей и настройка cookie сессии.
"""

from __future__ import annotations

import pytest
from app import auth
from fastapi import HTTPException


def _user(role: str) -> auth.CurrentUser:
    return auth.CurrentUser(
        id=1,
        username="user",
        full_name="Тестовый пользователь",
        role=role,
        role_label="Администратор" if role == "admin" else "Участник проекта",
        position="",
        display_position="Администратор" if role == "admin" else "Участник проекта",
    )


def test_require_admin_allows_admin_role() -> None:
    admin = _user("admin")
    assert auth.require_admin(admin) is admin


def test_require_admin_rejects_participant_role() -> None:
    with pytest.raises(HTTPException) as exc_info:
        auth.require_admin(_user("participant"))
    assert exc_info.value.status_code == 403


def test_get_current_user_rejects_missing_session_cookie() -> None:
    with pytest.raises(HTTPException) as exc_info:
        auth.get_current_user(sessionid=None)
    assert exc_info.value.status_code == 401


def test_cookie_kwargs_without_domain_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SK_SESSION_COOKIE_DOMAIN", raising=False)
    monkeypatch.delenv("SK_SESSION_COOKIE_SECURE", raising=False)
    kwargs = auth._cookie_kwargs()
    assert "domain" not in kwargs
    assert kwargs["secure"] is False
    assert kwargs["samesite"] == "lax"


def test_cookie_kwargs_with_domain_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SK_SESSION_COOKIE_DOMAIN", ".example.com")
    monkeypatch.setenv("SK_SESSION_COOKIE_SECURE", "true")
    kwargs = auth._cookie_kwargs()
    assert kwargs["domain"] == ".example.com"
    assert kwargs["secure"] is True
    # SameSite=None (требует Secure) — чтобы мобильное приложение (другой origin)
    # продолжало получать cookie сессии на кросс-сайт fetch-запросах.
    assert kwargs["samesite"] == "none"
