import { useEffect, useRef, useState } from "react";
import { fetchCurrentWeather, type CurrentWeatherResponse, type ProjectId } from "../api";
import "./HeaderWeather.css";

// Погода на объекте меняется не быстрее, чем раз в 10-15 минут (тот же порядок,
// что и TTL кэша на бэкенде) — опрашивать чаще не имеет смысла.
const REFRESH_INTERVAL_MS = 15 * 60 * 1000;

type WeatherCategory = "clear" | "cloudy" | "overcast" | "fog" | "drizzle" | "rain" | "snow" | "storm";

function categoryForCode(code: number | null): WeatherCategory {
  if (code === null) return "cloudy";
  if (code === 0) return "clear";
  if (code === 1 || code === 2) return "cloudy";
  if (code === 3) return "overcast";
  if (code === 45 || code === 48) return "fog";
  if ([51, 53, 55, 56, 57].includes(code)) return "drizzle";
  if ([61, 63, 65, 66, 67, 80, 81, 82].includes(code)) return "rain";
  if ([71, 73, 75, 77, 85, 86].includes(code)) return "snow";
  if ([95, 96, 99].includes(code)) return "storm";
  return "cloudy";
}

/** Простые монохромные иконки — цвет берётся из currentColor, чтобы вписаться в тему топбара. */
function WeatherIcon({ category, isDay, size = 22 }: { category: WeatherCategory; isDay: boolean | null; size?: number }) {
  const showMoon = isDay === false && (category === "clear" || category === "cloudy");
  const paths: Record<WeatherCategory, string> = {
    clear: showMoon
      ? "M15 3a7 7 0 1 0 6 10.5A7 7 0 0 1 15 3Z"
      : "M12 4v2M12 18v2M4 12h2M18 12h2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M6.3 17.7l1.4-1.4M16.3 7.7l1.4-1.4",
    cloudy: showMoon
      ? "M15 5a5 5 0 1 0 4 8.3A5 5 0 0 1 15 5Z M7 20a4 4 0 0 1-.6-7.96A5 5 0 0 1 16 11a3.5 3.5 0 0 1-.5 7H7Z"
      : "M12 5v1.5M6.3 7.3l1 1M18.7 7.3l-1 1 M7 20a4 4 0 0 1-.6-7.96A5 5 0 0 1 16 11a3.5 3.5 0 0 1-.5 7H7Z",
    overcast: "M6 19a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 16 10a3.5 3.5 0 0 1-.4 7H6Z M4 12a4 4 0 0 1 3-3.87",
    fog: "M4 10h16M4 14h16M4 18h12M6 6h10",
    drizzle: "M6 15a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 16 6a3.5 3.5 0 0 1-.4 7H6Z M8 18v2M12 18v2M16 18v2",
    rain: "M6 13a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 16 4a3.5 3.5 0 0 1-.4 7H6Z M7 17l-1.5 3M12 17l-1.5 3M17 17l-1.5 3",
    snow: "M6 13a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 16 4a3.5 3.5 0 0 1-.4 7H6Z M8 18v3M8 18l-1.5 1M8 18l1.5 1 M16 18v3M16 18l-1.5 1M16 18l1.5 1",
    storm: "M6 12a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 16 3a3.5 3.5 0 0 1-.4 7H6Z M13 14l-3 5h3l-2 4",
  };
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[category]} />
    </svg>
  );
}

function formatDayLabel(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00`);
  const label = date.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

interface HeaderWeatherProps {
  projectId: ProjectId;
  /** Показываем виджет только когда у проекта вообще есть координаты — без лишнего похода на сервер. */
  hasLocation: boolean;
}

export function HeaderWeather({ projectId, hasLocation }: HeaderWeatherProps) {
  const [weather, setWeather] = useState<CurrentWeatherResponse | null>(null);
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!hasLocation) {
      setWeather(null);
      return;
    }
    let cancelled = false;
    const load = () => {
      fetchCurrentWeather(projectId)
        .then((data) => {
          if (!cancelled) setWeather(data);
        })
        .catch(() => {
          if (!cancelled) setWeather(null);
        });
    };
    load();
    const timer = window.setInterval(load, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [projectId, hasLocation]);

  // Закрытие разворота по клику снаружи и по Escape — обычное поведение для поповера в шапке.
  useEffect(() => {
    if (!expanded) return;
    const onPointerDown = (event: PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setExpanded(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [expanded]);

  if (!hasLocation || !weather || weather.status === "no_location") return null;
  // Нет ни свежих, ни устаревших данных — честно ничего не показываем, а не нулевую температуру.
  if (weather.status === "unavailable" && weather.temperature === null) return null;

  const category = categoryForCode(weather.weather_code);
  const title = [weather.description_ru, weather.wind_speed !== null ? `ветер ${Math.round(weather.wind_speed)} м/с` : null, weather.is_stale ? "данные могут быть устаревшими" : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="sk-header-weather-wrap" ref={containerRef}>
      <button
        type="button"
        className={`sk-header-weather${weather.is_stale ? " sk-header-weather--stale" : ""}`}
        title={title}
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
      >
        <WeatherIcon category={category} isDay={weather.is_day} />
        {weather.temperature !== null && (
          <span className="sk-header-weather__temp">{Math.round(weather.temperature)}°</span>
        )}
      </button>

      {expanded && (
        <div className="sk-header-weather-popover" role="dialog" aria-label="Погода на объекте">
          <div className="sk-header-weather-popover__current">
            <span className="sk-header-weather-popover__icon-chip sk-header-weather-popover__icon-chip--lg">
              <WeatherIcon category={category} isDay={weather.is_day} size={34} />
            </span>
            <div>
              {weather.temperature !== null && (
                <div className="sk-header-weather-popover__temp">{Math.round(weather.temperature)}°</div>
              )}
              {weather.description_ru && (
                <div className="sk-header-weather-popover__desc">{weather.description_ru}</div>
              )}
            </div>
          </div>
          {weather.address && <div className="sk-header-weather-popover__address">{weather.address}</div>}
          <div className="sk-header-weather-popover__meta">
            {weather.wind_speed !== null && <span>Ветер: {Math.round(weather.wind_speed)} м/с</span>}
            {weather.is_stale && <span className="sk-header-weather-popover__stale">данные устарели</span>}
          </div>

          {weather.daily.length > 0 && (
            <div className="sk-header-weather-popover__daily">
              {weather.daily.map((day) => (
                <div key={day.date} className="sk-header-weather-popover__day">
                  <span className="sk-header-weather-popover__icon-chip">
                    <WeatherIcon category={categoryForCode(day.weather_code)} isDay={true} size={16} />
                  </span>
                  <span className="sk-header-weather-popover__day-label">{formatDayLabel(day.date)}</span>
                  <span className="sk-header-weather-popover__day-temps">
                    {day.temperature_max !== null && <>{Math.round(day.temperature_max)}°</>}
                    {day.temperature_min !== null && (
                      <span className="sk-header-weather-popover__day-min"> / {Math.round(day.temperature_min)}°</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
