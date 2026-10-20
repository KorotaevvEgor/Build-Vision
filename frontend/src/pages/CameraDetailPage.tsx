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
      <Link to={`/projects/${projectId}/cameras`} className="sk-back-button">
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

      <section className="sk-panel sk-camera-history">
        <header className="sk-camera-history__heading"><h2>Снимки камеры</h2><span>{camera.recent_observations.length} кадров · новые сначала</span></header>
        {camera.recent_observations.length === 0 && (
          <p className="sk-empty-state">Для этой камеры ещё нет сохранённых наблюдений.</p>
        )}
        <div className="sk-camera-history__grid">
          {camera.recent_observations.map((obs) => (
            <a key={obs.observation_id} className="sk-camera-tile sk-camera-history__frame" href={getObservationImageUrl(projectId, obs.observation_id).replace("?preview=true", "")} target="_blank" rel="noreferrer" aria-label={`Открыть снимок от ${new Date(obs.created_at).toLocaleString("ru-RU")}`}>
              <div className="sk-camera-tile__media">
                <img
                  className="sk-camera-tile__img"
                  src={getObservationImageUrl(projectId, obs.observation_id)}
                  crossOrigin="use-credentials"
                  alt={`Снимок от ${new Date(obs.created_at).toLocaleString("ru-RU")}`}
                  loading="lazy" decoding="async"
                />
                <span className="sk-camera-tile__badge">
                  <StatusBadge status={obs.overall_status} label={obs.overall_status_label_ru} />
                </span>
              </div>
              <div className="sk-camera-tile__footer">
                <span className="sk-camera-tile__time">{new Date(obs.created_at).toLocaleString("ru-RU")}</span>
              </div>
            </a>
          ))}
        </div>
      </section>
    </div>
  );
}
