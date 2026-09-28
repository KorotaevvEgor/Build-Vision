"""Адаптер прогноза погоды (Open-Meteo Forecast API).

Важно (см. план, раздел «Погодные риски: прогноз + график, а не виджет»):
  * Прогноз относится к БУДУЩИМ часам, не к моменту съёмки исторических
    снимков. Не сопоставлять прошлые фотографии с сегодняшним прогнозом.
  * При таймауте, ошибке сети или лимите API возвращается статус
    "unavailable", а не «рисков нет» — недоступность честно показывается.
  * Результат кэшируется на cache_ttl_minutes: запрос выполняется сервером,
    а не при каждом взаимодействии пользователя с картой.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import yaml

from .config import WEATHER_RULES_PATH

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Если внешний API недоступен (таймаут/ошибка сети), результат "unavailable" тоже
# кэшируется -- но на короткий срок, отдельный от обычного TTL успешного ответа. Без
# этого каждый запрос страницы во время сбоя/офлайна заново блокировался бы на полный
# сетевой таймаут (timeout_seconds, а у текущей погоды — даже дважды подряд из-за
# последовательного вызова прогноза на несколько дней) при каждой навигации пользователя
# по сайту -- именно это делало Главную/Календарный план визуально «не запускающимися».
_NEGATIVE_CACHE_SECONDS = 60

HOURLY_FIELDS = (
    "temperature_2m",
    "precipitation",
    "precipitation_probability",
    "wind_speed_10m",
    "wind_gusts_10m",
)


@dataclass(frozen=True)
class HourlyPoint:
    time_utc: str  # ISO 8601, час прогноза
    temperature_2m: float | None
    precipitation: float | None
    precipitation_probability: float | None
    wind_speed_10m: float | None
    wind_gusts_10m: float | None

    def value_of(self, factor: str) -> float | None:
        return getattr(self, factor, None)


@dataclass(frozen=True)
class ForecastResult:
    status: str  # "ok" | "unavailable"
    provider: str
    latitude: float
    longitude: float
    fetched_at: datetime | None
    hourly: list[HourlyPoint]
    error: str | None = None

    @property
    def is_stale(self) -> bool:
        if self.fetched_at is None:
            return True
        age_minutes = (datetime.now(timezone.utc) - self.fetched_at).total_seconds() / 60
        return age_minutes > _cache_ttl_minutes()


_cache_lock = threading.Lock()
_cache: dict[tuple[float, float], tuple[float, ForecastResult]] = {}
_config_cache: dict | None = None


def _load_config() -> dict:
    global _config_cache
    if _config_cache is None:
        _config_cache = yaml.safe_load(WEATHER_RULES_PATH.read_text(encoding="utf-8"))
    return _config_cache


def _cache_ttl_minutes() -> int:
    return int(_load_config().get("cache_ttl_minutes", 45))


def _forecast_hours() -> int:
    return int(_load_config().get("forecast_hours", 72))


def fetch_forecast(
    latitude: float,
    longitude: float,
    *,
    force_refresh: bool = False,
    timeout_seconds: float = 6.0,
) -> ForecastResult:
    """Получить почасовой прогноз, используя кэш с TTL из weather_rules.yaml."""
    key = (round(latitude, 4), round(longitude, 4))
    ttl_seconds = _cache_ttl_minutes() * 60

    with _cache_lock:
        cached = _cache.get(key)
    if cached and not force_refresh:
        cached_at, cached_result = cached
        fresh_for = ttl_seconds if cached_result.status == "ok" else _NEGATIVE_CACHE_SECONDS
        if time.monotonic() - cached_at < fresh_for:
            return cached_result

    hours = _forecast_hours()
    forecast_days = max(1, -(-hours // 24))  # округление вверх

    try:
        response = httpx.get(
            OPEN_METEO_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "hourly": ",".join(HOURLY_FIELDS),
                "forecast_days": forecast_days,
                "timezone": "UTC",
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        hourly_raw = payload.get("hourly", {})
        times = hourly_raw.get("time", [])

        points = [
            HourlyPoint(
                time_utc=times[i],
                temperature_2m=_safe_get(hourly_raw, "temperature_2m", i),
                precipitation=_safe_get(hourly_raw, "precipitation", i),
                precipitation_probability=_safe_get(hourly_raw, "precipitation_probability", i),
                wind_speed_10m=_safe_get(hourly_raw, "wind_speed_10m", i),
                wind_gusts_10m=_safe_get(hourly_raw, "wind_gusts_10m", i),
            )
            for i in range(min(len(times), hours))
        ]

        result = ForecastResult(
            status="ok",
            provider="open-meteo",
            latitude=latitude,
            longitude=longitude,
            fetched_at=datetime.now(timezone.utc),
            hourly=points,
        )
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        # Недоступность API не должна возвращать "рисков нет" — честный статус.
        # Результат всё равно кэшируется ниже (на _NEGATIVE_CACHE_SECONDS) -- без раннего return.
        if cached:
            _, stale_result = cached
            result = ForecastResult(
                status="unavailable",
                provider=stale_result.provider,
                latitude=latitude,
                longitude=longitude,
                fetched_at=stale_result.fetched_at,
                hourly=stale_result.hourly,
                error=str(exc),
            )
        else:
            result = ForecastResult(
                status="unavailable",
                provider="open-meteo",
                latitude=latitude,
                longitude=longitude,
                fetched_at=None,
                hourly=[],
                error=str(exc),
            )

    with _cache_lock:
        _cache[key] = (time.monotonic(), result)
    return result


def _safe_get(hourly_raw: dict, field: str, index: int) -> float | None:
    values = hourly_raw.get(field)
    if not values or index >= len(values):
        return None
    return values[index]


# --------------------------------------------------------------------------
# Текущая погода на объекте (виджет в шапке интерфейса)
# --------------------------------------------------------------------------

CURRENT_FIELDS = ("temperature_2m", "weather_code", "wind_speed_10m", "is_day")

#: Стандартный словарь WMO weather codes (таблица 4677), который использует
#: Open-Meteo. Русские подписи — свой, без привязки к конкретному языку API.
WEATHER_CODE_LABELS_RU: dict[int, str] = {
    0: "Ясно",
    1: "Преимущественно ясно",
    2: "Переменная облачность",
    3: "Пасмурно",
    45: "Туман",
    48: "Изморозь",
    51: "Морось: слабая",
    53: "Морось: умеренная",
    55: "Морось: сильная",
    56: "Ледяная морось: слабая",
    57: "Ледяная морось: сильная",
    61: "Дождь: слабый",
    63: "Дождь: умеренный",
    65: "Дождь: сильный",
    66: "Ледяной дождь: слабый",
    67: "Ледяной дождь: сильный",
    71: "Снег: слабый",
    73: "Снег: умеренный",
    75: "Снег: сильный",
    77: "Снежные зёрна",
    80: "Ливень: слабый",
    81: "Ливень: умеренный",
    82: "Ливень: сильный",
    85: "Снегопад: слабый",
    86: "Снегопад: сильный",
    95: "Гроза",
    96: "Гроза с небольшим градом",
    99: "Гроза с сильным градом",
}


def weather_code_label_ru(code: int | None) -> str | None:
    if code is None:
        return None
    return WEATHER_CODE_LABELS_RU.get(code, "Неизвестный код погоды")


@dataclass(frozen=True)
class CurrentWeatherResult:
    status: str  # "ok" | "unavailable"
    provider: str
    latitude: float
    longitude: float
    fetched_at: datetime | None
    temperature_2m: float | None
    weather_code: int | None
    wind_speed_10m: float | None
    is_day: bool | None
    error: str | None = None

    @property
    def is_stale(self) -> bool:
        if self.fetched_at is None:
            return True
        age_minutes = (datetime.now(timezone.utc) - self.fetched_at).total_seconds() / 60
        return age_minutes > _current_weather_cache_ttl_minutes()


_current_weather_cache_lock = threading.Lock()
_current_weather_cache: dict[tuple[float, float], tuple[float, CurrentWeatherResult]] = {}


def _current_weather_cache_ttl_minutes() -> int:
    # Текущая погода меняется быстрее, чем почасовой прогноз на часы вперёд —
    # кешируем её заметно короче (но не больше общего TTL из конфига, чтобы оставаться
    # в одном порядке с настройкой в weather_rules.yaml).
    return min(15, _cache_ttl_minutes())


def fetch_current_weather(
    latitude: float,
    longitude: float,
    *,
    force_refresh: bool = False,
    timeout_seconds: float = 6.0,
) -> CurrentWeatherResult:
    """Текущая погода для виджета в шапке интерфейса (Open-Meteo `current=...`).

    Отдельно от `fetch_forecast`: там почасовой прогноз на будущее для
    сравнения с графиком, здесь — реальные условия прямо сейчас, без привязки к часовой сетке.
    """
    key = (round(latitude, 4), round(longitude, 4))
    ttl_seconds = _current_weather_cache_ttl_minutes() * 60

    with _current_weather_cache_lock:
        cached = _current_weather_cache.get(key)
    if cached and not force_refresh:
        cached_at, cached_result = cached
        fresh_for = ttl_seconds if cached_result.status == "ok" else _NEGATIVE_CACHE_SECONDS
        if time.monotonic() - cached_at < fresh_for:
            return cached_result

    try:
        response = httpx.get(
            OPEN_METEO_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": ",".join(CURRENT_FIELDS),
                "timezone": "UTC",
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        current = payload.get("current", {})

        result = CurrentWeatherResult(
            status="ok",
            provider="open-meteo",
            latitude=latitude,
            longitude=longitude,
            fetched_at=datetime.now(timezone.utc),
            temperature_2m=current.get("temperature_2m"),
            weather_code=current.get("weather_code"),
            wind_speed_10m=current.get("wind_speed_10m"),
            is_day=bool(current.get("is_day")) if current.get("is_day") is not None else None,
        )
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        # Недоступность API не должна подменяться придуманными данными — честный статус.
        # Результат всё равно кэшируется ниже (на _NEGATIVE_CACHE_SECONDS) -- без раннего return.
        if cached:
            _, stale_result = cached
            result = CurrentWeatherResult(
                status="unavailable",
                provider=stale_result.provider,
                latitude=latitude,
                longitude=longitude,
                fetched_at=stale_result.fetched_at,
                temperature_2m=stale_result.temperature_2m,
                weather_code=stale_result.weather_code,
                wind_speed_10m=stale_result.wind_speed_10m,
                is_day=stale_result.is_day,
                error=str(exc),
            )
        else:
            result = CurrentWeatherResult(
                status="unavailable",
                provider="open-meteo",
                latitude=latitude,
                longitude=longitude,
                fetched_at=None,
                temperature_2m=None,
                weather_code=None,
                wind_speed_10m=None,
                is_day=None,
                error=str(exc),
            )

    with _current_weather_cache_lock:
        _current_weather_cache[key] = (time.monotonic(), result)
    return result


# --------------------------------------------------------------------------
# Прогноз на несколько дней (разворот виджета в шапке)
# --------------------------------------------------------------------------

DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
    "wind_speed_10m_max",
)

DAILY_FORECAST_DAYS = 5


@dataclass(frozen=True)
class DailyPoint:
    date: str  # ISO 8601, YYYY-MM-DD
    weather_code: int | None
    temperature_max: float | None
    temperature_min: float | None
    precipitation_probability_max: float | None
    wind_speed_max: float | None


@dataclass(frozen=True)
class DailyForecastResult:
    status: str  # "ok" | "unavailable"
    provider: str
    latitude: float
    longitude: float
    fetched_at: datetime | None
    days: list[DailyPoint]
    error: str | None = None

    @property
    def is_stale(self) -> bool:
        if self.fetched_at is None:
            return True
        age_minutes = (datetime.now(timezone.utc) - self.fetched_at).total_seconds() / 60
        return age_minutes > _cache_ttl_minutes()


_daily_forecast_cache_lock = threading.Lock()
_daily_forecast_cache: dict[tuple[float, float], tuple[float, DailyForecastResult]] = {}


def fetch_daily_forecast(
    latitude: float,
    longitude: float,
    *,
    days: int = DAILY_FORECAST_DAYS,
    force_refresh: bool = False,
    timeout_seconds: float = 6.0,
) -> DailyForecastResult:
    """Прогноз по дням (макс/мин температура, код погоды) для разворота виджета погоды.

    Отдельно от `fetch_forecast` (почасовой, для сравнения с графиком работ):
    здесь агрегированные посуточные значения, которые дешевле смотреть глазами
    в развороте шапки. Кэш — на общем TTL из weather_rules.yaml, как и `fetch_forecast`.
    """
    key = (round(latitude, 4), round(longitude, 4))
    ttl_seconds = _cache_ttl_minutes() * 60

    with _daily_forecast_cache_lock:
        cached = _daily_forecast_cache.get(key)
    if cached and not force_refresh:
        cached_at, cached_result = cached
        fresh_for = ttl_seconds if cached_result.status == "ok" else _NEGATIVE_CACHE_SECONDS
        if time.monotonic() - cached_at < fresh_for:
            return cached_result

    try:
        response = httpx.get(
            OPEN_METEO_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": ",".join(DAILY_FIELDS),
                "forecast_days": days,
                "timezone": "UTC",
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        daily_raw = payload.get("daily", {})
        dates = daily_raw.get("time", [])

        points = [
            DailyPoint(
                date=dates[i],
                weather_code=_safe_get(daily_raw, "weather_code", i),
                temperature_max=_safe_get(daily_raw, "temperature_2m_max", i),
                temperature_min=_safe_get(daily_raw, "temperature_2m_min", i),
                precipitation_probability_max=_safe_get(daily_raw, "precipitation_probability_max", i),
                wind_speed_max=_safe_get(daily_raw, "wind_speed_10m_max", i),
            )
            for i in range(len(dates))
        ]

        result = DailyForecastResult(
            status="ok",
            provider="open-meteo",
            latitude=latitude,
            longitude=longitude,
            fetched_at=datetime.now(timezone.utc),
            days=points,
        )
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        # Результат всё равно кэшируется ниже (на _NEGATIVE_CACHE_SECONDS) -- без раннего return.
        if cached:
            _, stale_result = cached
            result = DailyForecastResult(
                status="unavailable",
                provider=stale_result.provider,
                latitude=latitude,
                longitude=longitude,
                fetched_at=stale_result.fetched_at,
                days=stale_result.days,
                error=str(exc),
            )
        else:
            result = DailyForecastResult(
                status="unavailable",
                provider="open-meteo",
                latitude=latitude,
                longitude=longitude,
                fetched_at=None,
                days=[],
                error=str(exc),
            )

    with _daily_forecast_cache_lock:
        _daily_forecast_cache[key] = (time.monotonic(), result)
    return result
