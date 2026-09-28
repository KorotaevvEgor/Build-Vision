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
import { BarChart } from "../components/BarChart";
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

const EVENT_ACCENT: Record<string, "ok" | "warning" | "danger" | "info"> = {
  observation_analyzed: "info",
  deviation_detected: "danger",
  deviation_repeated: "warning",
  deviation_status_changed: "info",
  deviation_auto_resolved: "ok",
};

function stageProgressPercent(stage: StageSummary, today: Date): number {
  const start = new Date(stage.start_date);
  const end = new Date(stage.end_date);
  const totalDays = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
  if (totalDays <= 0) return 100;
  const clampedToday = today < start ? start : today > end ? end : today;
  const elapsedDays = Math.round((clampedToday.getTime() - start.getTime()) / 86_400_000) + 1;
  return Math.round(Math.max(0, Math.min(1, elapsedDays / totalDays)) * 1000) / 10;
}

function StatCard({ value, label, hint, accent }: { value: string | number; label: string; hint?: string; accent?: "ok" | "warning" | "danger" }) {
  return (
    <div className={`sk-panel sk-a-stat${accent ? ` sk-a-stat--${accent}` : ""}`}>
      <div className="sk-a-stat__value">{value}</div>
      <div className="sk-a-stat__label">{label}</div>
      {hint && <div className="sk-a-stat__hint">{hint}</div>}
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

  useEffect(() => {
    let cancelled = false;
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

  const deviationsData = analytics.deviations_by_day.map((d) => ({
    day: new Date(d.date).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }),
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
    <div className="sk-analytics-page">
      <h1>Аналитика</h1>
      <p className="sk-a-header__note">За всё время проекта, по всем сохранённым наблюдениям.</p>

      {!analytics.available && <p className="sk-panel sk-panel--error">База данных временно недоступна.</p>}

      <div className="sk-a-stats">
        <StatCard
          value={dashboard?.plan_completion_percent != null ? `${dashboard.plan_completion_percent}%` : "—"}
          label="Выполнение плана"
          hint={dashboard?.current_stage?.work_name ?? "Нет активного этапа"}
        />
        <StatCard value={`${onlineCameraCount}/${totalCameraCount}`} label="Камеры онлайн" />
        <StatCard value={analytics.equipment_counts.length} label="Типы техники" />
        <StatCard
          value={allDeviations.length}
          label="Отклонения всего"
          hint={criticalCount > 0 ? `критических: ${criticalCount}` : "критических нет"}
          accent={allDeviations.length === 0 ? "ok" : criticalCount > 0 ? "danger" : "warning"}
        />
        <StatCard
          value={forecast?.available && forecast.average_compliance_percent != null ? `${forecast.average_compliance_percent}%` : "—"}
          label="Средний темп"
        />
        <StatCard value={analytics.total_observations} label="Снимков всего" />
      </div>

      <div className="sk-panel">
        <h2>Отклонения по дням</h2>
        {deviationsData.length === 0 ? (
          <p className="sk-empty-state">Отклонений не зафиксировано.</p>
        ) : (
          <BarChart data={deviationsData} labelKey="day" valueKey="count" colorFor={() => "var(--sk-status-danger)"} />
        )}
      </div>

      <div className="sk-panel">
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
                    <span className="sk-a-stage-row__name">{stage.work_name}</span>
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

      <div className="sk-panel">
        <h2>Техника по классам</h2>
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

      <div className="sk-panel">
        <h2>Факторы риска</h2>
        {!forecast || !forecast.available ? (
          <p className="sk-empty-state">{forecast?.reason ?? "Прогноз недоступен."}</p>
        ) : forecast.risk_factors && forecast.risk_factors.length > 0 ? (
          <ul className="sk-risk-list">
            {forecast.risk_factors.map((f) => (
              <li key={f.key} className="sk-risk-list__item">
                <p>{f.message}</p>
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

      <div className="sk-panel">
        <h2>Отклонения по зонам</h2>
        {zoneRows.length === 0 ? (
          <p className="sk-empty-state">Отклонений по зонам не зафиксировано.</p>
        ) : (
          <table className="sk-table">
            <thead>
              <tr>
                <th>Зона</th>
                <th>Всего</th>
                <th>Критич.</th>
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

      <div className="sk-panel">
        <h2>Последние события</h2>
        {!events || events.length === 0 ? (
          <p className="sk-empty-state">Событий пока нет.</p>
        ) : (
          <ul className="sk-a-events-list">
            {events.map((event) => (
              <li key={event.id} className="sk-a-event">
                <span className={`sk-a-event-dot sk-a-event-dot--${EVENT_ACCENT[event.kind] ?? "info"}`} aria-hidden="true" />
                <div>
                  <div className="sk-a-event__title">{event.title}</div>
                  <div className="sk-a-events__time">
                    {new Date(event.created_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
                    {event.zone_name ? ` · ${event.zone_name}` : ""}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
