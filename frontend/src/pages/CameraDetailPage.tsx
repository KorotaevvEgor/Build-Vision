import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchCamera, getObservationImageUrl, type CameraDetail } from "../api";
import { useProject } from "../ProjectContext";
import { StatusBadge } from "../components/StatusBadge";
import "./CamerasPage.css";

export function CameraDetailPage() {
  const { projectId } = useProject();
  const { cameraId } = useParams<{ cameraId: string }>();
  const [camera, setCamera] = useState<CameraDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!cameraId) return;
    let cancelled = false;
    setCamera(null);
    setError(null);
    fetchCamera(projectId, cameraId)
      .then((data) => {
        if (!cancelled) setCamera(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, cameraId]);

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить камеру: {error}</div>;
  }
  if (!camera) {
    return <div className="sk-panel">Загрузка…</div>;
  }

  const online = Boolean(camera.stream_url);

  return (
    <div className="sk-cameras-page">
      <Link to={`/projects/${projectId}/cameras`} className="sk-deviation-panel__link">
        ← Все камеры
      </Link>

      <div className="sk-camera-detail__head">
        <div>
          <h1>{camera.name}</h1>
          <p className="sk-table__muted">Зона: {camera.zone_name}</p>
        </div>
        <span className={`sk-camera-detail__status${online ? " sk-camera-detail__status--online" : ""}`}>
          <span className="sk-camera-tile__dot sk-camera-detail__status-dot" />
          {online ? "В сети" : "Не в сети (скринкаст по расписанию)"}
        </span>
      </div>

      <div className="sk-camera-detail__actions">
        <Link to={`/projects/${projectId}/analysis`} className="sk-button">
          Проанализировать новый снимок
        </Link>
        <Link
          to={`/projects/${projectId}/cameras/${camera.camera_id}/zones`}
          className="sk-button sk-button--secondary"
        >
          Зоны на кадре
        </Link>
        {camera.stream_url && (
          <a
            href={camera.stream_url}
            target="_blank"
            rel="noreferrer"
            className="sk-button sk-button--secondary"
          >
            Смотреть трансляцию
          </a>
        )}
      </div>

      <div className="sk-panel" style={{ marginTop: "var(--sk-space-5)" }}>
        <h2>Последние сохранённые снимки</h2>
        {camera.recent_observations.length === 0 && (
          <p className="sk-empty-state">Для этой камеры ещё нет сохранённых наблюдений.</p>
        )}
        <div className="sk-cameras-grid">
          {camera.recent_observations.map((obs) => (
            <div key={obs.observation_id} className="sk-camera-tile sk-camera-tile--static">
              <div className="sk-camera-tile__media">
                <img
                  className="sk-camera-tile__img"
                  src={getObservationImageUrl(projectId, obs.observation_id)}
                  crossOrigin="use-credentials"
                  alt="Сохранённый снимок"
                />
                <span className="sk-camera-tile__badge">
                  <StatusBadge status={obs.overall_status} label={obs.overall_status_label_ru} />
                </span>
              </div>
              <div className="sk-camera-tile__footer">
                <span className="sk-camera-tile__time">{new Date(obs.created_at).toLocaleString("ru-RU")}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
