import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCameras, getObservationImageUrl, type CameraSummary } from "../api";
import { useProject } from "../ProjectContext";
import {CameraZonesCard} from "../components/CameraZonesCard";
import { StatusBadge } from "../components/StatusBadge";
import "./CamerasPage.css";

export function CamerasPage() {
  const { projectId } = useProject();
  const [cameras, setCameras] = useState<CameraSummary[] | null>(null);
  const [selectedId,setSelectedId]=useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setCameras(null);setSelectedId("");
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

  const selectedCamera=cameras.find(c=>c.camera_id===selectedId)??cameras[0];
  const onlineCount = cameras.filter((c) => c.stream_online).length;
  const offlineCount = cameras.length - onlineCount;

  return (
    <div className="sk-cameras-page">
      <h1>Камеры</h1>
      <p className="sk-demo-note">
        Снимки анализируются вручную через загрузку («Камера — AI-анализ») — реального
        видеопотока в датасете нет, здесь показан последний реально сохранённый анализ по камере.
      </p>

      {cameras.length > 0 && (
        <div className="sk-cameras-summary">
          <div className="sk-cameras-summary__item">
            <span className="sk-cameras-summary__dot sk-cameras-summary__dot--all" aria-hidden="true" />
            Всего камер: <b>{cameras.length}</b>
          </div>
          <div className="sk-cameras-summary__item">
            <span className="sk-cameras-summary__dot sk-cameras-summary__dot--online" aria-hidden="true" />
            Онлайн: <b>{onlineCount}</b>
          </div>
          {offlineCount > 0 && (
            <div className="sk-cameras-summary__item">
              <span className="sk-cameras-summary__dot sk-cameras-summary__dot--offline" aria-hidden="true" />
              Без трансляции (по расписанию): <b>{offlineCount}</b>
            </div>
          )}
        </div>
      )}

      {cameras.length === 0 && <p className="sk-empty-state">Камеры ещё не заведены.</p>}

      <div className="sk-cameras-workspace"><section className="sk-cameras-workspace__list sk-cameras-list-card" aria-label="Камеры проекта"><header><h2>Камеры</h2><p>Снимки и история наблюдений по каждой камере</p></header><div className="sk-cameras-grid">
        {cameras.map((camera) => {
          const online = Boolean(camera.stream_online);
          return (
            <article key={camera.camera_id} className="sk-camera-tile"><Link className="sk-camera-tile__select" aria-label={`Открыть камеру: ${camera.name}`} to={`/projects/${projectId}/cameras/${camera.camera_id}`}>
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
                <span
                  className={`sk-camera-tile__dot${online ? " sk-camera-tile__dot--online" : ""}`}
                  title={online ? "в сети" : "пока что не в сети (скринкаст)"}
                />
                {camera.latest_observation && (
                  <span className="sk-camera-tile__badge">
                    <StatusBadge
                      status={camera.latest_observation.overall_status}
                      label={camera.latest_observation.overall_status_label_ru}
                    />
                  </span>
                )}
                <div className="sk-camera-tile__scrim">
                  <div className="sk-camera-tile__name">{camera.name}</div>
                  <div className="sk-camera-tile__zone">{camera.zone_name}</div>
                </div>
              </div>
              </Link>
              <div className="sk-zones-card__body sk-camera-tile__details"><ul>
                <li><span>Сохранено кадров</span><strong className="sk-camera-frame-count">{camera.observation_count ?? '—'}</strong></li>
                <li><span>Последний снимок</span><small>{camera.latest_observation ? new Date(camera.latest_observation.created_at).toLocaleString("ru-RU") : 'Снимков пока нет'}</small></li>
                <li><span>Получение кадров</span><small>{online ? 'Видеотрансляция' : 'По расписанию'}</small></li>
              </ul></div>
              <div className="sk-camera-tile__footer"><p>Снимки и история наблюдений выбранной камеры.</p><Link className="sk-button" to={`/projects/${projectId}/cameras/${camera.camera_id}`}>Открыть камеру →</Link></div>
            </article>
          );
        })}
      </div></section><aside className="sk-cameras-workspace__zones" aria-label="Зоны выбранной камеры">{selectedCamera?<><div className="sk-zones-camera-select">{cameras.length>1&&<label>Камера для разметки<select value={selectedCamera.camera_id} onChange={e=>setSelectedId(e.target.value)}>{cameras.map(c=><option key={c.camera_id} value={c.camera_id}>{c.name}</option>)}</select></label>}</div><CameraZonesCard key={`${projectId}-${selectedCamera.camera_id}`} cameraId={selectedCamera.camera_id}/></>:<div className="sk-panel"><h2>Зоны на кадре</h2><p className="sk-empty-state">Добавьте камеру, чтобы настроить зоны наблюдения.</p></div>}</aside></div>
    </div>
  );
}
