import { useEffect, useState } from "react";
import { fetchWeatherRisks, type WeatherRiskResponse } from "../api";
import { useProject } from "../ProjectContext";
import "./WeatherRiskPanel.css";

const FACTOR_LABELS_RU: Record<string, string> = {
  temperature_2m: "Температура",
  precipitation: "Осадки",
  precipitation_probability: "Вероятность осадков",
  wind_speed_10m: "Скорость ветра",
  wind_gusts_10m: "Порывы ветра",
};

function formatHour(iso: string): string {
  const [, time] = iso.split("T");
  return time ?? iso;
}

export function WeatherRiskPanel() {
  const { projectId } = useProject();
  const [data, setData] = useState<WeatherRiskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchWeatherRisks(projectId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <div className="sk-panel sk-weather-panel">
      <div className="sk-weather-panel__header">
        <h2>Погодные риски (72 часа)</h2>
        {data?.location_is_demo && <span className="sk-weather-panel__demo-tag">демо-координаты</span>}
      </div>

      {error && <p className="sk-weather-panel__error">Не удалось загрузить прогноз: {error}</p>}

      {!error && !data && <p className="sk-empty-state">Загрузка прогноза…</p>}

      {data && data.status === "unavailable" && (
        <p className="sk-weather-panel__unavailable">
          Прогноз временно недоступен{data.error ? `: ${data.error}` : ""}. Анализ снимков и график продолжают работать.
        </p>
      )}

      {data && data.status === "ok" && (
        <>
          <p className="sk-weather-panel__meta">
            {data.provider} · {data.fetched_at ? new Date(data.fetched_at).toLocaleString("ru-RU") : "—"}
            {data.is_stale && " · устарело"}
          </p>

          {data.risk_periods.length === 0 ? (
            <p className="sk-empty-state">На ближайшие 72 часа рисков не выявлено.</p>
          ) : (
            <ul className="sk-weather-risk-list">
              {data.risk_periods.map((period, index) => (
                <li key={index} className="sk-weather-risk-item">
                  <div className="sk-weather-risk-item__header">
                    <strong>{period.work_name}</strong>
                    <span className="sk-weather-risk-item__window">
                      {formatHour(period.start_time_utc)}–{formatHour(period.end_time_utc)} UTC
                    </span>
                  </div>
                  <p>{period.message}</p>
                  <p className="sk-weather-risk-item__value">
                    {FACTOR_LABELS_RU[period.factor] ?? period.factor}: пик {period.peak_value}
                    {period.units} (порог {period.comparison === "gte" ? "≥" : "≤"} {period.threshold}
                    {period.units})
                  </p>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
