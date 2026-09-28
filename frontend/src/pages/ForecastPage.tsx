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
import "./ForecastPage.css";

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

const STATUS_RU: Record<ScheduleNetworkResponse["status"], string> = {
  behind: "Отставание от графика",
  on_track: "В графике",
  ahead: "Опережение графика",
};

export function ForecastPage() {
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
    return <div className="sk-panel sk-panel--error">Не удалось загрузить прогноз: {error}</div>;
  }
  if (!network) {
    return <div className="sk-panel">Загрузка прогноза…</div>;
  }

  const shifting = network.available ? network.stages.filter((s) => s.shifts_project_finish) : [];
  const unverified = network.available
    ? network.stages.filter((s) => network.unverified_stage_ids.includes(s.stage_id))
    : [];

  return (
    <div className="sk-forecast-page" id="sk-forecast-print-area">
      <div className="sk-f-header">
        <div>
          <h1>Прогноз сдачи объекта</h1>
          <p className="sk-f-header__note">
            Расчёт на реальных данных фотоконтроля и погоды — не ML-предсказание. «%» ниже — эвристика (доля
            наблюдений без отклонений), а не измеренный физический прогресс.
          </p>
        </div>
        <button type="button" className="sk-button sk-f-pdf-btn" onClick={() => window.print()}>
          Скачать PDF-отчёт
        </button>
      </div>

      {!network.available ? (
        <div className="sk-panel sk-panel--error">
          <p>{network.reason}</p>
          {network.cycle.length > 0 && (
            <p className="sk-table__muted">
              Работы в цикле: {network.cycle.join(", ")}. Расчёт прогноза невозможен, пока цикл связей не разорван.
            </p>
          )}
        </div>
      ) : (
        <>
          {/* --- Главный вердикт: сдаём в срок или нет --- */}
          <div className={`sk-f-verdict sk-f-verdict--${network.status}`}>
            <div className="sk-f-verdict__status">
              <span className="sk-f-verdict__label">Вердикт</span>
              <strong>{STATUS_RU[network.status]}</strong>
              {network.shift_days !== 0 && (
                <span className="sk-f-verdict__shift">
                  {network.shift_days > 0 ? "+" : "−"}
                  {Math.abs(network.shift_days)} {plural(network.shift_days)} к плану
                </span>
              )}
            </div>
            <div className="sk-f-verdict__dates">
              <div>
                <span className="sk-f-verdict__label">Плановая сдача</span>
                <strong>{network.baseline_finish_date ? formatDate(network.baseline_finish_date) : "—"}</strong>
              </div>
              <div className="sk-f-verdict__arrow">→</div>
              <div>
                <span className="sk-f-verdict__label">Прогнозная сдача</span>
                {network.projected_finish_date ? (
                  <div className="sk-f-verdict__value-row">
                    <strong className={`sk-f-verdict__value--${network.shift_days > 0 ? "bad" : "ok"}`}>
                      {formatDate(network.projected_finish_date)}
                    </strong>
                    <Link
                      to={`/projects/${projectId}/forecast/why`}
                      className="sk-f-verdict__why-btn"
                      title="Почему прогноз именно такой — подробнее"
                      aria-label="Почему прогноз именно такой — подробнее"
                    >
                      ?
                    </Link>
                  </div>
                ) : (
                  <strong>—</strong>
                )}
              </div>
            </div>
          </div>

          <div className="sk-f-row2">
            {/* --- Текущий этап: план/факт --- */}
            <div className="sk-panel sk-f-stage-panel">
              <h2>Текущий этап</h2>
              {!forecast || !forecast.available ? (
                <p className="sk-empty-state">{forecast?.reason ?? "Нет активного этапа для прогноза на сегодня."}</p>
              ) : (
                <>
                  <div className="sk-f-stage-panel__name">{forecast.work_name}</div>
                  <div className="sk-progress-flex">
                    <div
                      className="sk-progress-ring"
                      style={{
                        background: `conic-gradient(var(--sk-status-ok) 0 ${forecast.average_compliance_percent ?? 0}%, var(--sk-surface-muted) ${forecast.average_compliance_percent ?? 0}% 100%)`,
                      }}
                    >
                      <span>
                        {forecast.average_compliance_percent != null ? `${forecast.average_compliance_percent}%` : "—"}
                      </span>
                    </div>
                    <div className="sk-plan-fact">
                      <div>
                        <small>Плановое завершение</small>
                        <strong>{forecast.planned_end_date}</strong>
                      </div>
                      <div>
                        <small>Прогнозное завершение</small>
                        <strong className={forecast.delay_days && forecast.delay_days > 0 ? "sk-f-verdict__value--bad" : undefined}>
                          {forecast.projected_end_date}
                        </strong>
                      </div>
                      <div>
                        <small>Отставание</small>
                        <strong className={forecast.delay_days && forecast.delay_days > 0 ? "sk-f-verdict__value--bad" : "sk-f-verdict__value--ok"}>
                          {forecast.delay_days && forecast.delay_days > 0 ? `+${forecast.delay_days} дн.` : "нет"}
                        </strong>
                      </div>
                    </div>
                  </div>
                  <p className="sk-table__muted" style={{ marginTop: "var(--sk-space-3)" }}>
                    Наблюдений за период этапа: {forecast.observation_count}. Текущий темп:{" "}
                    {forecast.current_compliance_percent != null ? `${forecast.current_compliance_percent}%` : "нет данных"}.
                  </p>
                </>
              )}
              <Link to={`/projects/${projectId}/schedule`} className="sk-f-panel-link">
                Открыть календарный план →
              </Link>
            </div>

            {/* --- Факторы риска --- */}
            <div className="sk-panel sk-f-risks-panel">
              <h2>Факторы риска</h2>
              {!forecast || !forecast.available ? (
                <p className="sk-empty-state">Нет данных для оценки факторов риска.</p>
              ) : forecast.risk_factors && forecast.risk_factors.length > 0 ? (
                <table className="sk-table">
                  <thead>
                    <tr>
                      <th>Риск</th>
                      <th>Влияние</th>
                    </tr>
                  </thead>
                  <tbody>
                    {forecast.risk_factors.map((f) => (
                      <tr key={f.key}>
                        <td>{f.message}</td>
                        <td>
                          <span className={`sk-risk-badge sk-risk-badge--${SEVERITY_ACCENT[f.severity]}`}>
                            {SEVERITY_LABEL[f.severity]}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="sk-empty-state">По текущему этапу значимых факторов риска не выявлено.</p>
              )}
            </div>
          </div>

          <WeatherRiskPanel />

          {(shifting.length > 0 || unverified.length > 0) && (
            <div className="sk-f-row2">
              {shifting.length > 0 && (
                <div className="sk-panel sk-f-alert-panel sk-f-alert-panel--danger">
                  <h2>Что двигает дату сдачи</h2>
                  <ul>
                    {shifting.map((stage) => (
                      <li key={stage.stage_id}>
                        <strong>{stage.work_name}</strong>: отставание {stage.delay_days} {plural(stage.delay_days)} при
                        запасе {stage.total_float_days} {plural(stage.total_float_days)}. {stage.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {unverified.length > 0 && (
                <div className="sk-panel sk-f-alert-panel sk-f-alert-panel--warning">
                  <h2>Вне контроля по снимкам</h2>
                  <p className="sk-table__muted">
                    Плановый срок истёк, но подтверждающих снимков нет — это не значит, что работы выполнены.
                  </p>
                  <ul>
                    {unverified.map((stage) => (
                      <li key={stage.stage_id}>
                        {stage.work_name} (до {formatDate(stage.planned_end_date)})
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
