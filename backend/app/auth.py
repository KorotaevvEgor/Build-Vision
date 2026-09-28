"""Аутентификация и роли поверх системы пользователей Django.

Осознанное архитектурное решение (см. план): переиспользуем
`django.contrib.auth` (проверка пароля, модель User) и
`django.contrib.sessions` (та же таблица `django_session`, что и у Django
admin) вместо отдельной JWT-системы. FastAPI уже инициализирует Django через
`django_bridge.ensure_django_ready()` для чтения справочников, поэтому может
напрямую использовать эти API — не нужно ни новой зависимости, ни
дублирования логики хеширования паролей.

Два пользователя, залогинившиеся с одним и тем же браузером на
основном домене и его поддомене admin, используют один и тот же cookie
`sessionid`, если задан `SK_SESSION_COOKIE_DOMAIN=.your-domain.example` (см. .env.example
в корне) — Администратор входит один раз и получает доступ к обоим.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, Response

from . import django_bridge

SESSION_COOKIE_NAME = "sessionid"
_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14  # 2 недели


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    full_name: str
    role: str
    role_label: str
    position: str
    display_position: str
    # Поля карточки профиля со значениями по умолчанию: они нужны интерфейсу, но не
    # нужны проверке прав. Без умолчаний любой код, собирающий пользователя вручную
    # (тесты, подмена зависимости в FastAPI), ломается при каждом расширении профиля.
    has_avatar: bool = False
    date_joined: str = ""
    last_login: str | None = None


def _cookie_kwargs() -> dict:
    domain = os.environ.get("SK_SESSION_COOKIE_DOMAIN") or None
    secure = os.environ.get("SK_SESSION_COOKIE_SECURE", "false").lower() == "true"
    # Мобильное приложение (Capacitor) грузится с `https://localhost` и делает к API
    # запросы на другой origin — браузерный/WebView-движок не отправит cookie
    # с `SameSite=Lax` на таких кросс-сайт fetch/XHR-запросах. На `secure=True`
    # (прод, HTTPS) используется `SameSite=None` (требует Secure, иначе браузеры
    # отклонят cookie) — для локальной разработки по HTTP остаётся `Lax`.
    samesite = "none" if secure else "lax"
    kwargs: dict = {"samesite": samesite, "secure": secure, "path": "/"}
    if domain:
        kwargs["domain"] = domain
    return kwargs


def authenticate_user(username: str, password: str):
    """Возвращает объект Django User при успешной проверке пароля, иначе None."""
    if not django_bridge.ensure_django_ready():
        raise HTTPException(503, "База данных недоступна — вход временно невозможен")

    from django.contrib.auth import authenticate

    return authenticate(username=username, password=password)


def create_session(user, session_key: str | None = None) -> str:
    """Создаёт сессию Django для пользователя, возвращает session_key."""
    from django.contrib.auth import login
    from django.contrib.sessions.backends.db import SessionStore
    from django.http import HttpRequest

    request = HttpRequest()
    request.session = SessionStore(session_key)
    # Штатный login сохраняет backend и auth hash, меняет ключ при входе
    # и не оставляет сессию другого пользователя при переключении аккаунта.
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.set_expiry(_SESSION_MAX_AGE_SECONDS)
    request.session.save()
    return request.session.session_key


def destroy_session(session_key: str) -> None:
    from django.contrib.sessions.backends.db import SessionStore

    SessionStore(session_key).delete()


def user_to_current_user(user) -> CurrentUser:
    from core.models import UserProfile

    profile = getattr(user, "profile", None)
    if profile is None:
        # На случай пользователя, созданного до появления UserProfile —
        # честно откатываемся на роль "Участник" по умолчанию, не роняем вход.
        profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={
                "role": UserProfile.Role.ADMIN
                if user.is_superuser and user.is_staff
                else UserProfile.Role.PARTICIPANT,
            },
        )
    role = profile.role if user.is_staff else UserProfile.Role.PARTICIPANT
    role_label = dict(UserProfile.Role.choices)[role]
    return CurrentUser(
        id=user.id,
        username=user.username,
        full_name=user.get_full_name() or user.username,
        role=role,
        role_label=role_label,
        position=profile.position,
        display_position=profile.position or role_label,
        has_avatar=bool(profile.avatar_path),
        date_joined=user.date_joined.isoformat(),
        last_login=user.last_login.isoformat() if user.last_login else None,
    )


def get_user_from_session(session_key: str | None) -> CurrentUser | None:
    if not session_key or not django_bridge.ensure_django_ready():
        return None

    from django.contrib.auth import get_user
    from django.contrib.sessions.backends.db import SessionStore
    from django.http import HttpRequest

    request = HttpRequest()
    request.session = SessionStore(session_key)
    # get_user проверяет срок сессии, активность, backend и auth hash.
    # После смены пароля старый cookie больше не даёт доступ к API.
    user = get_user(request)
    if not user.is_authenticated or not user.is_active:
        return None
    return user_to_current_user(user)


def set_session_cookie(response: Response, session_key: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_key,
        max_age=_SESSION_MAX_AGE_SECONDS,
        httponly=True,
        **_cookie_kwargs(),
    )


def clear_session_cookie(response: Response) -> None:
    kwargs = _cookie_kwargs()
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path=kwargs["path"],
        domain=kwargs.get("domain"),
        secure=kwargs["secure"],
        httponly=True,
        samesite=kwargs["samesite"],
    )


def get_current_user(sessionid: str | None = Cookie(default=None)) -> CurrentUser:
    """FastAPI-зависимость: 401, если нет валидной сессии."""
    user = get_user_from_session(sessionid)
    if user is None:
        raise HTTPException(401, "Требуется вход в систему")
    return user


def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """FastAPI-зависимость: 403, если роль пользователя не «Администратор»."""
    if current_user.role != "admin":
        raise HTTPException(403, "Действие доступно только администратору")
    return current_user


def refresh_session_auth_hash(session_key: str | None, user) -> None:
    """Пересчитывает хеш пароля в текущей сессии после смены пароля.

    Django хранит в сессии хеш от пароля (`_auth_user_hash`) и сравнивает его при
    каждом запросе (`django.contrib.auth.get_user`) — без обновления смена собственного
    пароля сразу же разлогинивала бы текущую вкладку/сессию.
    """
    if not session_key:
        return
    from django.contrib.auth import HASH_SESSION_KEY
    from django.contrib.sessions.backends.db import SessionStore

    session = SessionStore(session_key)
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.save()


def end_all_sessions_for_user(user_id: int) -> int:
    """Удаляет все активные сессии данного пользователя («выйти везде»).

    Django не ведёт прямой связи сессия → пользователь, поэтому приходится пройти
    по всем неистёкшим сессиям и декодировать каждую, чтобы сравнить `_auth_user_id`.
    Возвращает число удалённых сессий.
    """
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    removed = 0
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        data = session.get_decoded()
        if str(data.get("_auth_user_id")) == str(user_id):
            session.delete()
            removed += 1
    return removed
