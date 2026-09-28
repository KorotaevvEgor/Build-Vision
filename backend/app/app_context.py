"""Единый срез конфигурации проекта на один запрос: график, правила, геометрия, погода.

Загружается заново на каждый вызов (см. исторический комментарий в main.py) —
правила и график редактируются через Django admin, и изменения должны быть
видны без перезапуска FastAPI.

``site=None`` — legacy-проект (см. project_scope.require_legacy_project_access):
загрузчики (schedule.py/rules_config.py/weather_rules_config.py) в этом случае
сами фильтруют по ``ConstructionSite.is_legacy=True`` и допускают файловый
откат при недоступности БД. Явно переданный ``site`` — строгий scope на этот
проект без отката на демо-файлы (см. план «API изоляция»): пустой новый
проект честно возвращает пустые график/правила, а не демоданные.
"""

from __future__ import annotations

from .rules_config import EquipmentRules, load_equipment_rules
from .schedule import Schedule, load_schedule, load_site_geojson, site_centroid
from .weather_rules_config import WeatherRule, load_weather_rules


class AppContext:
    schedule: Schedule
    rules: EquipmentRules
    site_geojson: dict
    weather_rules: list[WeatherRule]
    site_latitude: float | None
    site_longitude: float | None

    def __init__(self, site=None) -> None:
        self.site = site
        self.schedule = load_schedule(site=site)
        self.rules = load_equipment_rules(site=site)
        self.site_geojson = load_site_geojson(site=site)
        self.weather_rules = load_weather_rules(site=site)
        centroid = site_centroid(self.site_geojson)
        if centroid is not None:
            self.site_latitude, self.site_longitude = centroid
        else:
            # Новый проект без границы/точки на карте — честное отсутствие
            # местоположения, а не подстановка московской демоплощадки.
            self.site_latitude = None
            self.site_longitude = None


def get_context(site=None) -> AppContext:
    return AppContext(site=site)
