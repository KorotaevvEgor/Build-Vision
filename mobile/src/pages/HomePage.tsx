import { useEffect, useState } from "react";
import { fetchDashboard, type DashboardResponse } from "../api";
import { useAuth } from "../AuthContext";
import { useProject } from "../ProjectContext";
import "./HomePage.css";

export function HomePage() {
  const { user } = useAuth();
  const { projectId } = useProject();
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDashboard(null);
    setError(null);
    fetchDashboard(projectId)
      .then((data) => {
        if (!cancelled) setDashboard(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить сводку: {error}</div>;
  }
  if (!dashboard) {
    return <div className="sk-panel">Загрузка…</div>;
  }

  return (
    <div>
      <h1>Здравствуйте, {user?.full_name.split(" ")[0] ?? "инженер"}</h1>

      {!dashboard.available && (
        <p className="sk-panel sk-panel--error">БД временно недоступна — сводка показывает нулевые значения.</p>
      )}

      <div className="sk-home-stats">
        <div className="sk-panel sk-home-stat">
          <div className="sk-home-stat__value">{dashboard.zone_count}</div>
          <div className="sk-home-stat__label">Зон</div>
        </div>
        <div className="sk-panel sk-home-stat">
          <div className="sk-home-stat__value">{dashboard.camera_count}</div>
          <div className="sk-home-stat__label">Камер</div>
        </div>
        <div className="sk-panel sk-home-stat">
          <div className="sk-home-stat__value">{dashboard.deviation_count_24h}</div>
          <div className="sk-home-stat__label">Отклонений за 24ч</div>
        </div>
      </div>

      {dashboard.top_risk_factor && dashboard.top_risk_factor.severity === "high" && (
        <div className="sk-panel sk-home-risk">
          <div className="sk-home-risk__title">⚠ Высокий риск отклонения</div>
          <div className="sk-table__muted">{dashboard.top_risk_factor.message}</div>
        </div>
      )}

      <div className="sk-panel" style={{ marginTop: "var(--sk-space-4)" }}>
        <h2>Зоны</h2>
        {dashboard.zones.length === 0 && <p className="sk-empty-state">Зон не найдено.</p>}
        <ul className="sk-home-zone-list">
          {dashboard.zones.map((zone) => (
            <li key={zone.zone_id} className="sk-home-zone-list__item">
              <span>{zone.name}</span>
              <span className="sk-table__muted">
                {zone.latest_observation ? zone.latest_observation.overall_status_label_ru : "нет данных"}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
