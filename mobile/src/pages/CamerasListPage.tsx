import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCameras, getObservationImageUrl, type CameraSummary } from "../api";
import { useProject } from "../ProjectContext";
import { StatusBadge } from "../components/StatusBadge";
import "./CamerasListPage.css";

export function CamerasListPage() {
  const { projectId } = useProject();
  const [cameras, setCameras] = useState<CameraSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setCameras(null);
    setError(null);
    fetchCameras(projectId)
      .then((data) => {
        if (!cancelled) setCameras(data.cameras);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить камеры: {error}</div>;
  }
  if (!cameras) {
    return <div className="sk-panel">Загрузка камер…</div>;
  }

  const onlineCount = cameras.filter((c) => c.stream_url).length;

  return (
    <div>
      <h1>Камеры</h1>
      {cameras.length > 0 && (
        <p className="sk-table__muted" style={{ marginBottom: "var(--sk-space-3)" }}>
          Онлайн: {onlineCount} из {cameras.length}
        </p>
      )}
      {cameras.length === 0 && <p className="sk-empty-state">Камеры ещё не заведены.</p>}

      <div className="sk-cameras-grid">
        {cameras.map((camera) => {
          const online = Boolean(camera.stream_url);
          return (
            <Link key={camera.camera_id} to={`/projects/${projectId}/cameras/${camera.camera_id}`} className="sk-camera-tile">
              <div className="sk-camera-tile__media">
                {camera.latest_observation ? (
                  <img
                    className="sk-camera-tile__img"
                    src={getObservationImageUrl(projectId, camera.latest_observation.observation_id)}
                    crossOrigin="use-credentials"
                    alt={`Последний снимок камеры ${camera.name}`}
                  />
                ) : (
                  <div className="sk-camera-tile__img sk-camera-tile__img--empty">Нет снимков</div>
                )}
                <span className={`sk-camera-tile__dot${online ? " sk-camera-tile__dot--online" : ""}`} />
                {camera.latest_observation && (
                  <span className="sk-camera-tile__badge">
                    <StatusBadge status={camera.latest_observation.overall_status} label={camera.latest_observation.overall_status_label_ru} />
                  </span>
                )}
                <div className="sk-camera-tile__scrim">
                  <div className="sk-camera-tile__name">{camera.name}</div>
                  <div className="sk-camera-tile__zone">{camera.zone_name}</div>
                </div>
              </div>
              <div className="sk-camera-tile__footer">
                {camera.latest_observation ? (
                  <span className="sk-camera-tile__time">{new Date(camera.latest_observation.created_at).toLocaleString("ru-RU")}</span>
                ) : (
                  <span className="sk-empty-state">Ещё не анализировалась</span>
                )}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
