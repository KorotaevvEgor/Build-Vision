import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchAnalytics,
  fetchDashboard,
  fetchDeviations,
  fetchProjectEvents,
  fetchSite,
  fetchStageForecast,
  type AnalyticsResponse,
  type DashboardResponse,
  type DeviationRecord,
  type ForecastResponse,
  type ProjectEventItem,
  type SiteResponse,
  type StageSummary,
} from "../api";
import { useProject } from "../ProjectContext";
import "./AnalyticsPage.css";

const CLASS_COLOR_VARS: Record<string, string> = {
  excavator: "var(--sk-class-excavator)",
  dump_truck: "var(--sk-class-dump-truck)",
  mobile_crane: "var(--sk-class-mobile-crane)",
  crane_manipulator: "var(--sk-class-crane-manipulator)",
  concrete_mixer: "var(--sk-class-concrete-mixer)",
  bulldozer: "var(--sk-class-bulldozer)",
  road_roller: "var(--sk-class-road-roller)",
  truck: "var(--sk-class-truck)",
};

function classColor(classKey: string): string {
  return CLASS_COLOR_VARS[classKey] ?? "var(--sk-class-unknown)";
}

const SEVERITY_RU: Record<string, string> = { high: "Высокий риск", medium: "Средний риск", low: "Низкий риск" };
const SEVERITY_ACCENT: Record<string, "ok" | "warning" | "danger"> = {
  high: "danger",
  medium: "warning",
  low: "ok",
};

const EVENT_ACCENT: Record<string, "ok" | "warning" | "danger" | "info"> = {
  observation_analyzed: "info",
  deviation_detected: "danger",
  deviation_repeated: "warning",
  deviation_status_changed: "info",
  deviation_auto_resolved: "ok",
};

/**
 * Честная эвристика: доля прошедших дней периода этапа, не физический прогресс
 * (та же формула, что и в backend/app/insights.py::_stage_progress_percent и на Главной).
 */
function stageProgressPercent(stage: StageSummary, today: Date): number {
  const start = new Date(stage.start_date);
  const end = new Date(stage.end_date);
  const totalDays = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
  if (totalDays <= 0) return 100;
  const clampedToday = today < start ? start : today > end ? end : today;
  const elapsedDays = Math.round((clampedToday.getTime() - start.getTime()) / 86_400_000) + 1;
  return Math.round(Math.max(0, Math.min(1, elapsedDays / totalDays)) * 1000) / 10;
}

function StatCard({
  icon,
  value,
  label,
  hint,
  accent,
}: {
  icon: string;
  value: string | number;
  label: string;
  hint?: string;
  accent?: "ok" | "warning" | "danger";
}) {
  return (
    <div className="sk-panel sk-a-stat">
      <span className={`sk-a-stat__icon${accent ? ` sk-a-stat__icon--${accent}` : ""}`} aria-hidden="true">
        {icon}
      </span>
      <div>
        <div className="sk-a-stat__value">{value}</div>
        <div className="sk-a-stat__label">{label}</div>
        {hint && <div className={`sk-a-stat__hint${accent ? ` sk-a-stat__hint--${accent}` : ""}`}>{hint}</div>}
      </div>
    </div>
  );
}

function BarChart({
  data,
  labelKey,
  valueKey,
  colorFor,
}: {
  data: Record<string, unknown>[];
  labelKey: string;
  valueKey: string;
  colorFor?: (label: string) => string;
}) {
  const max = Math.max(1, ...data.map((d) => Number(d[valueKey])));
  return (
    <div className="sk-bar-chart">
      {data.map((d, index) => {
        const label = String(d[labelKey]);
        const value = Number(d[valueKey]);
        return (
          <div key={index} className="sk-bar-chart__col">
            <div className="sk-bar-chart__track">
              <div
                className="sk-bar-chart__bar"
                style={{ height: `${(value / max) * 100}%`, background: colorFor ? colorFor(label) : undefined }}
                title={`${label}: ${value}`}
              />
            </div>
            <div className="sk-bar-chart__label">{label}</div>
            <div className="sk-bar-chart__value">{value}</div>
          </div>
        );
      })}
    </div>
  );
}

export function AnalyticsPage() {
  const { projectId } = useProject();
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [site, setSite] = useState<SiteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [deviations, setDeviations] = useState<DeviationRecord[] | null>(null);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [events, setEvents] = useState<ProjectEventItem[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setAnalytics(null);
    setSite(null);
    setError(null);
    // days=0 — без нижней границы по дате: аналитика по всему проекту, а не за выбранный период.
    Promise.all([fetchAnalytics(projectId, 0), fetchSite(projectId)])
      .then(([a, s]) => {
        if (cancelled) return;
        setAnalytics(a);
        setSite(s);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Отдельные, некритичные для первого рендера источники — не блокируют основной экран.
  useEffect(() => {
    let cancelled = false;
    setDashboard(null);
    setDeviations(null);
    setForecast(null);
    setEvents(null);
    fetchDashboard(projectId)
      .then((d) => !cancelled && setDashboard(d))
      .catch(() => undefined);
    fetchDeviations(projectId)
      .then((d) => !cancelled && setDeviations(d.items))
      .catch(() => !cancelled && setDeviations([]));
    fetchStageForecast(projectId)
      .then((f) => !cancelled && setForecast(f))
      .catch(() => !cancelled && setForecast({ available: false, reason: "Не удалось загрузить прогноз" }));
    fetchProjectEvents(projectId, 12)
      .then((e) => !cancelled && setEvents(e.items))
      .catch(() => !cancelled && setEvents([]));
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить аналитику: {error}</div>;
  }
  if (!analytics || !site) {
    return <div className="sk-panel">Загрузка аналитики…</div>;
  }

  const today = new Date();
  const allDeviations = deviations ?? [];
  const criticalCount = allDeviations.filter((d) => d.severity === "critical").length;

  const onlineCameraCount = dashboard ? dashboard.cameras.filter((c) => c.stream_url).length : 0;
  const totalCameraCount = dashboard?.cameras.length ?? 0;

  const deviationsData = analytics.deviations_by_month.map((d) => ({
    // "YYYY-MM" надёжно парсится как дата только с днём: без него New Date("2026-04") в
    // некоторых движках трактуется в UTC и может съехать на месяц назад в местном часовом поясе.
    day: new Date(`${d.month}-01`).toLocaleDateString("ru-RU", { month: "short", year: "numeric" }),
    count: d.count,
  }));

  const zoneAgg = new Map<string, { zoneName: string; total: number; critical: number }>();
  for (const d of allDeviations) {
    const entry = zoneAgg.get(d.zone_name) ?? { zoneName: d.zone_name, total: 0, critical: 0 };
    entry.total += 1;
    if (d.severity === "critical") entry.critical += 1;
    zoneAgg.set(d.zone_name, entry);
  }
  const zoneRows = Array.from(zoneAgg.values()).sort((a, b) => b.total - a.total);

  return (
    <div className="sk-analytics-page" id="sk-analytics-print-area">
      <div className="sk-a-header">
        <div>
          <h1>Аналитика</h1>
          <p className="sk-a-header__note">За всё время проекта, по всем сохранённым наблюдениям.</p>
        </div>
        <button type="button" className="sk-button sk-a-pdf-btn" onClick={() => window.print()}>
          Скачать PDF-отчёт
        </button>
      </div>

      {!analytics.available && (
        <p className="sk-panel sk-panel--error" style={{ marginTop: "var(--sk-space-3)" }}>
          База данных временно недоступна — графики ниже пустые, а не выдуманные.
        </p>
      )}

      <div className="sk-a-stats">
        <StatCard
          icon="📊"
          value={dashboard?.plan_completion_percent !== null && dashboard?.plan_completion_percent !== undefined ? `${dashboard.plan_completion_percent}%` : "—"}
          label="Выполнение плана"
          hint={dashboard?.current_stage?.work_name ?? "Нет активного этапа"}
        />
        <StatCard
          icon="🎥"
          value={`${onlineCameraCount}/${totalCameraCount}`}
          label="Камеры онлайн"
          hint="реальный видеопоток"
        />
        <StatCard icon="🚜" value={analytics.equipment_counts.length} label="Типы техники" hint="распознано всего" />
        <StatCard
          icon="⚠"
          value={allDeviations.length}
          label="Отклонения (всего)"
          hint={criticalCount > 0 ? `в т.ч. критических: ${criticalCount}` : "критических нет"}
          accent={allDeviations.length === 0 ? "ok" : criticalCount > 0 ? "danger" : "warning"}
        />
        <StatCard
          icon="📈"
          value={forecast?.available && forecast.average_compliance_percent != null ? `${forecast.average_compliance_percent}%` : "—"}
          label="Средний темп (без отклонений)"
          hint={forecast?.available ? forecast.work_name : "Нет активного этапа"}
        />
        <StatCard icon="📸" value={analytics.total_observations} label="Снимков всего" hint="сохранённых наблюдений" />
      </div>

      <div className="sk-a-row3">
        <div className="sk-panel sk-a-chart-panel">
          <h2>Отклонения по месяцам</h2>
          {deviationsData.length === 0 ? (
            <p className="sk-empty-state">Отклонений не зафиксировано.</p>
          ) : (
            <BarChart data={deviationsData} labelKey="day" valueKey="count" colorFor={() => "var(--sk-status-danger)"} />
          )}
        </div>

        <div className="sk-panel sk-a-stages-panel">
          <h2>Этапы графика — % по времени</h2>
          {site.stages.length === 0 ? (
            <p className="sk-empty-state">Этапы графика не заданы.</p>
          ) : (
            <ul className="sk-a-stage-list">
              {site.stages.map((stage) => {
                const percent = stageProgressPercent(stage, today);
                return (
                  <li key={stage.stage_id} className="sk-a-stage-row">
                    <div className="sk-a-stage-row__top">
                      <span className="sk-a-stage-row__name" title={stage.work_name}>
                        {stage.work_name}
                      </span>
                      <span className="sk-a-stage-row__percent">{percent}%</span>
                    </div>
                    <div className="sk-progress-bar">
                      <div className="sk-progress-bar__fill" style={{ width: `${percent}%` }} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="sk-panel sk-a-risks-panel">
          <h2>Факторы риска</h2>
          {!forecast || !forecast.available ? (
            <p className="sk-empty-state">{forecast?.reason ?? "Прогноз недоступен."}</p>
          ) : forecast.risk_factors && forecast.risk_factors.length > 0 ? (
            <ul className="sk-a-risk-list">
              {forecast.risk_factors.map((f) => (
                <li key={f.key} className={`sk-a-risk-item sk-a-risk-item--${SEVERITY_ACCENT[f.severity]}`}>
                  <div className="sk-a-risk-item__top">{SEVERITY_RU[f.severity] ?? f.severity}</div>
                  <p className="sk-a-risk-item__message">{f.message}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="sk-empty-state">По активному этапу факторов риска не выявлено.</p>
          )}
          <Link to={`/projects/${projectId}/forecast`} className="sk-a-panel-link">
            Подробнее в прогнозе →
          </Link>
        </div>
      </div>

      <div className="sk-a-row3">
        <div className="sk-panel sk-a-chart-panel">
          <h2>Техника по классам</h2>
          <p className="sk-table__muted">Всего наблюдений: {analytics.total_observations}</p>
          {analytics.equipment_counts.length === 0 ? (
            <p className="sk-empty-state">Техника не распознана уверенно ни на одном снимке.</p>
          ) : (
            <BarChart
              data={analytics.equipment_counts}
              labelKey="label_ru"
              valueKey="count"
              colorFor={(label) => {
                const entry = analytics.equipment_counts.find((e) => e.label_ru === label);
                return entry ? classColor(entry.class_key) : "var(--sk-class-unknown)";
              }}
            />
          )}
        </div>

        <div className="sk-panel sk-a-zones-panel">
          <h2>Отклонения по зонам</h2>
          {zoneRows.length === 0 ? (
            <p className="sk-empty-state">Отклонений по зонам не зафиксировано.</p>
          ) : (
            <table className="sk-table">
              <thead>
                <tr>
                  <th>Зона</th>
                  <th>Всего</th>
                  <th>Критические</th>
                </tr>
              </thead>
              <tbody>
                {zoneRows.map((z) => (
                  <tr key={z.zoneName}>
                    <td>{z.zoneName}</td>
                    <td>{z.total}</td>
                    <td className={z.critical > 0 ? "sk-quantity-mismatch" : undefined}>{z.critical}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <Link to={`/projects/${projectId}/notifications`} className="sk-a-panel-link">
            Все отклонения →
          </Link>
        </div>

        <div className="sk-panel sk-a-forecast-panel">
          <h2>Прогноз завершения этапа</h2>
          {!forecast || !forecast.available ? (
            <p className="sk-empty-state">{forecast?.reason ?? "Прогноз недоступен."}</p>
          ) : (
            <>
              <div className="sk-a-forecast__stage">{forecast.work_name}</div>
              <div className="sk-a-forecast__dates">
                <div>
                  <span className="sk-table__muted">План</span>
                  <div>{forecast.planned_end_date}</div>
                </div>
                <div>
                  <span className="sk-table__muted">Прогноз</span>
                  <div>{forecast.projected_end_date}</div>
                </div>
              </div>
              <div
                className={`sk-a-forecast__delay${
                  forecast.delay_days && forecast.delay_days > 0 ? " sk-a-forecast__delay--bad" : " sk-a-forecast__delay--ok"
                }`}
              >
                {forecast.delay_days && forecast.delay_days > 0 ? `+${forecast.delay_days} дней к плану` : "В срок"}
              </div>
              {forecast.average_compliance_percent != null && (
                <p className="sk-table__muted">
                  Средний темп без отклонений: {forecast.average_compliance_percent}%
                  {forecast.current_compliance_percent != null && ` (сейчас: ${forecast.current_compliance_percent}%)`}
                </p>
              )}
            </>
          )}
          <Link to={`/projects/${projectId}/forecast`} className="sk-a-panel-link">
            Открыть прогноз →
          </Link>
        </div>
      </div>

      <div className="sk-panel sk-a-events-panel">
        <h2>Последние события</h2>
        {!events || events.length === 0 ? (
          <p className="sk-empty-state">Событий пока нет.</p>
        ) : (
          <table className="sk-table">
            <thead>
              <tr>
                <th>Время</th>
                <th>Событие</th>
                <th>Детали</th>
                <th>Зона</th>
                <th>Источник</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td className="sk-a-events__time">
                    {new Date(event.created_at).toLocaleString("ru-RU", {
                      day: "2-digit",
                      month: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td>
                    <span className={`sk-a-event-dot sk-a-event-dot--${EVENT_ACCENT[event.kind] ?? "info"}`} aria-hidden="true" />
                    {event.kind_label_ru}
                  </td>
                  <td>{event.title}</td>
                  <td>{event.zone_name ?? "—"}</td>
                  <td>{event.actor ?? "Система"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
