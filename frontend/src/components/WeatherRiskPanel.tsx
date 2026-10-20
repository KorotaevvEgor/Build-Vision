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
  // Формат от Open-Meteo: "2026-09-15T11:00" (без секунд/зоны, уже UTC).
  const [, time] = iso.split("T");
  return time ?? iso;
}

interface Props {
  /**
   * Название идущей сейчас работы. Если задано и реальных погодных рисков нет, показывается
   * демонстрационный риск (явно помечен) — чтобы на показе была видна сама механика карточки.
   * Реальные риски от Open-Meteo всегда имеют приоритет.
   */
  demoRiskWorkName?: string;
}

/** Демонстрационный риск: завтра, окно 03:00–09:00 UTC. Значения выдуманы для показа. */
function demoRiskWindowLabel(): string {
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const date = tomorrow.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
  return `${date} · 03:00–09:00 UTC`;
}

export function WeatherRiskPanel({ demoRiskWorkName }: Props = {}) {
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

  const showDemoRisk =
    Boolean(demoRiskWorkName) && data?.status === "ok" && data.risk_periods.length === 0;

  return (
    <div className="sk-panel sk-weather-panel">
      <div className="sk-weather-panel__header">
        <h2>Погодные риски (72 часа)</h2>
        {data?.location_is_demo && (
          <span className="sk-weather-panel__demo-tag">демонстрационные координаты</span>
        )}
        {showDemoRisk && <span className="sk-weather-panel__demo-tag">демонстрационный риск</span>}
      </div>

      {error && <p className="sk-weather-panel__error">Не удалось загрузить прогноз: {error}</p>}

      {!error && !data && <p className="sk-empty-state">Загрузка прогноза…</p>}

      {data && data.status === "unavailable" && (
        <p className="sk-weather-panel__unavailable">
          Прогноз временно недоступен{data.error ? `: ${data.error}` : ""}. Это не означает
          отсутствие рисков — анализ снимков и график продолжают работать.
        </p>
      )}

      {data && data.status === "ok" && (
        <>
          <p className="sk-weather-panel__meta">
            Источник: {data.provider} · получено:{" "}
            {data.fetched_at ? new Date(data.fetched_at).toLocaleString("ru-RU") : "—"}
            {data.is_stale && " · данные устарели"}
          </p>

          {data.risk_periods.length === 0 && showDemoRisk ? (
            <ul className="sk-weather-risk-list">
              <li className="sk-weather-risk-item sk-weather-risk-item--demo">
                <div className="sk-weather-risk-item__header">
                  <strong>{demoRiskWorkName}</strong>
                  <span className="sk-weather-risk-item__window">{demoRiskWindowLabel()}</span>
                </div>
                <p>
                  Ожидается сильный дождь с порывистым ветром. Бетонирование перекрытий и подача бетона краном
                  будут приостановлены: влажность нарушает технологию укладки, а ветер свыше допустимого
                  предела делает небезопасной работу автокрана. Уложенный бетон потребует укрытия, что затянет
                  график.
                </p>
                <p className="sk-weather-risk-item__value">
                  Осадки: пик 5,4 мм/ч (порог ≥ 2,5 мм/ч) · Порывы ветра: пик 16 м/с (порог ≥ 12 м/с)
                </p>
                <p className="sk-weather-risk-item__impact">
                  Возможная задержка этапа: <strong>до 2 дней</strong>
                </p>
              </li>
            </ul>
          ) : data.risk_periods.length === 0 ? (
            <p className="sk-empty-state">
              На ближайшие 72 часа периодов, затрагивающих активные этапы, не выявлено.
            </p>
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
                    {period.units} (порог {period.comparison === "gte" ? "≥" : "≤"}{" "}
                    {period.threshold}
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
