"""Разрешение доступа к проекту по project_id из URL.

Единая точка проверки для всех `/api/projects/{project_id}/...` маршрутов
(см. план «выбор и создание проектов», раздел «Данные и разграничение
доступа»). Контекст проекта передаётся явно как FastAPI-зависимость —
никакого общего «выбранного проекта» в серверной сессии не хранится.

Правила ошибок (см. план):
* Проект не существует ИЛИ участник не имеет к нему членства — 404
  (чужой проект не должен быть обнаружим перебором ID).
* Роль не позволяет действие (например, создание проекта не-администратором)
  — 403.
* БД недоступна — 503, а не подмена на пустой/демонстрационный результат.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException

from . import auth, django_bridge


@dataclass(frozen=True)
class ProjectScope:
    """Снимок проекта на один запрос: минимум данных, нужных обработчикам."""

    project_id: int
    name: str
    is_legacy: bool


def _ensure_db_ready() -> None:
    if not django_bridge.ensure_django_ready():
        raise HTTPException(503, "База данных недоступна")


def user_can_access_site(current_user: auth.CurrentUser, site) -> bool:
    if current_user.role == "admin":
        return True
    from core.models import ProjectMembership

    return ProjectMembership.objects.filter(site_id=site.pk, user_id=current_user.id).exists()


def get_project_scope(
    project_id: int,
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> ProjectScope:
    """FastAPI-зависимость для проектных маршрутов: `project_id` берётся из пути."""
    _ensure_db_ready()
    from core.models import ConstructionSite

    site = ConstructionSite.objects.filter(pk=project_id).first()
    if site is None or not user_can_access_site(current_user, site):
        # Чужой/несуществующий проект — единая явная ошибка, не 403: не
        # подтверждаем существование проекта пользователю без доступа.
        raise HTTPException(404, "Проект не найден или недоступен")
    return ProjectScope(project_id=site.pk, name=site.name, is_legacy=site.is_legacy)


def get_project_site(
    project_id: int,
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
):
    """Как get_project_scope, но возвращает саму ORM-модель ConstructionSite.

    Используется там, где обработчику нужны дополнительные поля (адрес,
    статус, координаты, геометрия), а не только идентификатор.
    """
    _ensure_db_ready()
    from core.models import ConstructionSite

    site = ConstructionSite.objects.filter(pk=project_id).first()
    if site is None or not user_can_access_site(current_user, site):
        raise HTTPException(404, "Проект не найден или недоступен")
    return site


def require_legacy_project_access(
    current_user: auth.CurrentUser = Depends(auth.get_current_user),
) -> auth.CurrentUser:
    """Зависимость для старых `/api/...` маршрутов (см. план «Миграция и совместимость»).

    Обращается только к закреплённому legacy-проекту. Отсутствие привязки
    или отозванный доступ — явная ошибка, без выбора другого проекта.
    """
    _ensure_db_ready()
    from core.models import ConstructionSite

    site = ConstructionSite.objects.filter(is_legacy=True).first()
    if site is None:
        raise HTTPException(503, "Базовый (legacy) проект не настроен на сервере")
    if not user_can_access_site(current_user, site):
        raise HTTPException(403, "Доступ к базовому проекту отозван")
    return current_user


def get_legacy_site():
    """Возвращает ORM-модель legacy-проекта либо явно падает, без отката на другой проект."""
    _ensure_db_ready()
    from core.models import ConstructionSite

    site = ConstructionSite.objects.filter(is_legacy=True).first()
    if site is None:
        raise HTTPException(503, "Базовый (legacy) проект не настроен на сервере")
    return site
