import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchScheduleNetwork,
  fetchStageForecast,
  type ForecastResponse,
  type RiskFactor,
  type ScheduleNetworkResponse,
} from "../api";
import { useProject } from "../ProjectContext";
import { WeatherRiskPanel } from "../components/WeatherRiskPanel";
import "./ForecastExplanationPage.css";

const SEVERITY_LABEL: Record<RiskFactor["severity"], string> = {
  high: "Высокое",
  medium: "Среднее",
  low: "Низкое",
};

const SEVERITY_ACCENT: Record<RiskFactor["severity"], "danger" | "warning" | "ok"> = {
  high: "danger",
  medium: "warning",
  low: "ok",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** Склонение дней: 1 день, 2 дня, 5 дней. */
function plural(days: number): string {
  const n = Math.abs(days) % 100;
  const last = n % 10;
  if (n > 10 && n < 20) return "дней";
  if (last === 1) return "день";
  if (last >= 2 && last <= 4) return "дня";
  return "дней";
}

export function ForecastExplanationPage() {
  const { projectId } = useProject();
  const [network, setNetwork] = useState<ScheduleNetworkResponse | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setNetwork(null);
    setForecast(null);
    setError(null);
    Promise.all([fetchScheduleNetwork(projectId), fetchStageForecast(projectId)])
      .then(([n, f]) => {
        if (cancelled) return;
        setNetwork(n);
        setForecast(f);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить объяснение прогноза: {error}</div>;
  }
  if (!network) {
    return <div className="sk-panel">Загрузка…</div>;
  }
  if (!network.available) {
    return (
      <div className="sk-f-why-page">
        <Link to={`/projects/${projectId}/forecast`} className="sk-a-panel-link">
          ← Назад к прогнозу
        </Link>
        <div className="sk-panel sk-panel--error" style={{ marginTop: "var(--sk-space-4)" }}>
          {network.reason}
        </div>
      </div>
    );
  }

  const leafStages = network.stages.filter((s) => !s.is_summary);
  const shifting = leafStages.filter((s) => s.shifts_project_finish);
  const absorbed = leafStages.filter((s) => s.delay_days > 0 && !s.shifts_project_finish);
  const unverified = network.stages.filter((s) => network.unverified_stage_ids.includes(s.stage_id));

  const shiftDays = network.shift_days;
  const shiftSentence =
    shiftDays === 0
      ? "Прогнозная дата совпадает с плановой — отставаний, влияющих на срок сдачи, не выявлено."
      : shiftDays > 0
        ? `Прогнозная дата сдвинута на ${shiftDays} ${plural(shiftDays)} позже плана.`
        : `Прогноз опережает план на ${Math.abs(shiftDays)} ${plural(shiftDays)}.`;

  return (
    <div className="sk-f-why-page">
      <Link to={`/projects/${projectId}/forecast`} className="sk-a-panel-link">
        ← Назад к прогнозу
      </Link>

      <h1>Почему прогнозная сдача именно такая</h1>
      <p className="sk-f-why-summary">
        План: <strong>{network.baseline_finish_date ? formatDate(network.baseline_finish_date) : "—"}</strong> ·
        Прогноз: <strong>{network.projected_finish_date ? formatDate(network.projected_finish_date) : "—"}</strong>.{" "}
        {shiftSentence}
      </p>

      <div className="sk-panel sk-f-why-panel">
        <h2>Что реально двигает срок сдачи</h2>
        <p className="sk-table__muted">
          Эти работы — на критическом пути или их отставание превышает собственный запас времени, поэтому каждый
          день их задержки напрямую сдвигает дату сдачи объекта.
        </p>
        {shifting.length === 0 ? (
          <p className="sk-empty-state">Таких работ сейчас нет.</p>
        ) : (
          <ul className="sk-f-why-list">
            {shifting.map((s) => (
              <li key={s.stage_id} className="sk-f-why-item sk-f-why-item--danger">
                <div className="sk-f-why-item__top">
                  <strong>{s.work_name}</strong>
                  <span className="sk-f-why-item__delay">
                    +{s.delay_days} {plural(s.delay_days)}
                  </span>
                </div>
                <p>{s.reason}</p>
                <p className="sk-table__muted">
                  Запас времени: {s.total_float_days} {plural(s.total_float_days)}
                  {s.is_critical && " · критический путь"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="sk-panel sk-f-why-panel">
        <h2>Где был промах, но срок сдачи не пострадал</h2>
        <p className="sk-table__muted">
          Эти работы тоже отстают от плана, но у них есть запас времени — отставание пока не сдвигает дату сдачи
          объекта. Если запас исчерпается, они перейдут в предыдущий список.
        </p>
        {absorbed.length === 0 ? (
          <p className="sk-empty-state">Таких работ сейчас нет.</p>
        ) : (
          <ul className="sk-f-why-list">
            {absorbed.map((s) => (
              <li key={s.stage_id} className="sk-f-why-item sk-f-why-item--warning">
                <div className="sk-f-why-item__top">
                  <strong>{s.work_name}</strong>
                  <span className="sk-f-why-item__delay">
                    +{s.delay_days} {plural(s.delay_days)}
                  </span>
                </div>
                <p>{s.reason}</p>
                <p className="sk-table__muted">
                  Запас времени: {s.total_float_days} {plural(s.total_float_days)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="sk-panel sk-f-why-panel">
        <h2>Факторы риска текущего этапа</h2>
        {!forecast || !forecast.available ? (
          <p className="sk-empty-state">Нет активного этапа для оценки рисков.</p>
        ) : forecast.risk_factors && forecast.risk_factors.length > 0 ? (
          <ul className="sk-f-why-list">
            {forecast.risk_factors.map((f) => (
              <li key={f.key} className={`sk-f-why-item sk-f-why-item--${SEVERITY_ACCENT[f.severity]}`}>
                <div className="sk-f-why-item__top">
                  <strong>{SEVERITY_LABEL[f.severity]} влияние</strong>
                </div>
                <p>{f.message}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="sk-empty-state">По текущему этапу значимых факторов риска не выявлено.</p>
        )}
      </div>

      <WeatherRiskPanel />

      {unverified.length > 0 && (
        <div className="sk-panel sk-f-why-panel">
          <h2>Слепые зоны контроля</h2>
          <p className="sk-table__muted">
            Плановый срок этих работ истёк, но подтверждающих снимков нет — прогноз не может учесть их реальный
            статус, это тоже потенциальный риск для срока сдачи.
          </p>
          <ul className="sk-f-why-list">
            {unverified.map((s) => (
              <li key={s.stage_id} className="sk-f-why-item">
                {s.work_name} (до {formatDate(s.planned_end_date)})
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
