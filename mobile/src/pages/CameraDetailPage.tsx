import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  fetchCamera,
  fetchObservation,
  fetchZoneStagesOnDate,
  getObservationImageUrl,
  type CameraDetail,
  type ObservationDetail,
  type ObservationSummary,
  type ZoneStageOnDate,
} from "../api";
import { useProject } from "../ProjectContext";
import { EquipmentIcon } from "../components/EquipmentIcons";
import "./CameraDetailPage.css";

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

export function CameraDetailPage() {
  const { projectId } = useProject();
  const { cameraId } = useParams<{ cameraId: string }>();
  const [camera, setCamera] = useState<CameraDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [historyIndex, setHistoryIndex] = useState(0);
  const [observation, setObservation] = useState<ObservationDetail | null>(null);
  const [observationError, setObservationError] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const [frameSize, setFrameSize] = useState<{ width: number; height: number } | null>(null);
  const [historyStageInfo, setHistoryStageInfo] = useState<ZoneStageOnDate | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!cameraId) return;
    let cancelled = false;
    setCamera(null);
    setError(null);
    setHistoryIndex(0);
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

  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const update = () => setFrameSize({ width: el.clientWidth, height: el.clientHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [camera]);

  const history: ObservationSummary[] = camera?.recent_observations ?? [];
  const displayed: ObservationSummary | null = history[historyIndex] ?? camera?.latest_observation ?? null;
  const isHistoryMode = historyIndex > 0;
  const hasOlderHistory = historyIndex < history.length - 1;

  useEffect(() => {
    let cancelled = false;
    setObservation(null);
    setObservationError(null);
    setImageSize(null);
    if (!displayed) return;
    fetchObservation(projectId, displayed.observation_id)
      .then((data) => !cancelled && setObservation(data))
      .catch((err: Error) => !cancelled && setObservationError(err.message));
    return () => {
      cancelled = true;
    };
  }, [projectId, displayed?.observation_id]);

  useEffect(() => {
    let cancelled = false;
    setHistoryStageInfo(null);
    if (!isHistoryMode || !camera || !displayed) return;
    const onDate = displayed.observed_date ?? displayed.created_at.slice(0, 10);
    fetchZoneStagesOnDate(projectId, camera.zone_id, onDate)
      .then((data) => !cancelled && setHistoryStageInfo(data.stages[0] ?? null))
      .catch(() => !cancelled && setHistoryStageInfo(null));
    return () => {
      cancelled = true;
    };
  }, [projectId, isHistoryMode, camera, displayed]);

  const detectedGroups = useMemo(() => {
    const byClass = new Map<string, { classKey: string; label: string; count: number }>();
    for (const d of observation?.detections ?? []) {
      if (!d.in_taxonomy || d.ambiguous) continue;
      const existing = byClass.get(d.class_key);
      if (existing) existing.count += 1;
      else byClass.set(d.class_key, { classKey: d.class_key, label: d.label_ru, count: 1 });
    }
    return Array.from(byClass.values());
  }, [observation]);

  const displayRect = useMemo(() => {
    if (!imageSize || !frameSize || !imageSize.width || !imageSize.height || !frameSize.width || !frameSize.height) {
      return null;
    }
    const imageRatio = imageSize.width / imageSize.height;
    const frameRatio = frameSize.width / frameSize.height;
    let width: number;
    let height: number;
    if (frameRatio > imageRatio) {
      height = frameSize.height;
      width = height * imageRatio;
    } else {
      width = frameSize.width;
      height = width / imageRatio;
    }
    return { width, height, offsetX: (frameSize.width - width) / 2, offsetY: (frameSize.height - height) / 2 };
  }, [imageSize, frameSize]);

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить камеру: {error}</div>;
  }
  if (!camera) {
    return <div className="sk-panel">Загрузка…</div>;
  }

  const online = Boolean(camera.stream_url);

  return (
    <div>
      <Link to={`/projects/${projectId}/cameras`} className="sk-deviation-panel__link">
        ← Все камеры
      </Link>

      <div className="sk-camera-detail__head">
        <div>
          <h1>{camera.name}</h1>
          <p className="sk-table__muted">Зона: {camera.zone_name}</p>
        </div>
        <span className={`sk-camera-detail__status${online && !isHistoryMode ? " sk-camera-detail__status--online" : ""}`}>
          {online && !isHistoryMode ? "В сети" : isHistoryMode ? "Архив" : "Не в сети"}
        </span>
      </div>

      <div className="sk-panel sk-camera-card">
        <div className="sk-camera-card__head">
          {displayed && <span className="sk-camera-card__head-time">{new Date(displayed.created_at).toLocaleString("ru-RU")}</span>}
          {history.length > 1 && (
            <div className="sk-camera-card__history-controls">
              <button
                type="button"
                className="sk-camera-card__history-btn"
                onClick={() => setHistoryIndex((i) => i + 1)}
                disabled={!hasOlderHistory}
              >
                ‹ Назад
              </button>
              <button
                type="button"
                className="sk-camera-card__history-btn"
                onClick={() => setHistoryIndex((i) => Math.max(0, i - 1))}
                disabled={!isHistoryMode}
              >
                Вперёд ›
              </button>
              {isHistoryMode && (
                <button type="button" className="sk-camera-card__history-btn sk-camera-card__history-btn--live" onClick={() => setHistoryIndex(0)}>
                  Онлайн
                </button>
              )}
            </div>
          )}
        </div>

        <div className="sk-camera-card__frame" ref={frameRef}>
          {displayed ? (
            <>
              <img
                className="sk-camera-card__image"
                src={getObservationImageUrl(projectId, displayed.observation_id)}
                crossOrigin="use-credentials"
                alt={`Снимок камеры ${camera.name}`}
                onLoad={(event) => {
                  const target = event.currentTarget;
                  setImageSize({ width: target.naturalWidth, height: target.naturalHeight });
                }}
              />
              {imageSize &&
                displayRect &&
                observation?.detections.map((detection, index) => {
                  const naturalWidth = imageSize.width || 1;
                  const naturalHeight = imageSize.height || 1;
                  const [x1, y1, x2, y2] = detection.bbox;
                  const color = detection.ambiguous
                    ? "var(--sk-status-warning)"
                    : !detection.in_taxonomy
                      ? "var(--sk-class-unknown)"
                      : classColor(detection.class_key);
                  return (
                    <div
                      key={index}
                      className={`sk-bbox${detection.ambiguous ? " sk-bbox--ambiguous" : ""}`}
                      style={{
                        left: `${displayRect.offsetX + (x1 / naturalWidth) * displayRect.width}px`,
                        top: `${displayRect.offsetY + (y1 / naturalHeight) * displayRect.height}px`,
                        width: `${((x2 - x1) / naturalWidth) * displayRect.width}px`,
                        height: `${((y2 - y1) / naturalHeight) * displayRect.height}px`,
                        borderColor: color,
                      }}
                    >
                      <span className="sk-bbox__label" style={{ backgroundColor: color }}>
                        {detection.label_ru} {(detection.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  );
                })}
            </>
          ) : (
            <div className="sk-camera-card__empty">С этой камеры ещё нет снимков.</div>
          )}
        </div>

        {detectedGroups.length > 0 && (
          <div className="sk-camera-card__legend">
            {detectedGroups.map((g) => (
              <div key={g.classKey} className="sk-camera-card__legend-item">
                <EquipmentIcon classKey={g.classKey} style={{ color: classColor(g.classKey) }} />
                {g.label} <b>{g.count}</b>
              </div>
            ))}
          </div>
        )}
        {observationError && <p className="sk-panel--error">Не удалось загрузить разбор снимка: {observationError}</p>}
      </div>

      {isHistoryMode && (
        <div className="sk-panel" style={{ marginTop: "var(--sk-space-4)" }}>
          <h2>Этап на дату снимка</h2>
          {historyStageInfo ? (
            <>
              <div className="sk-current-stage__title">{historyStageInfo.work_name}</div>
              <p className="sk-table__muted">
                {historyStageInfo.start_date} – {historyStageInfo.end_date}
              </p>
            </>
          ) : (
            <p className="sk-empty-state">На эту дату активных этапов не было.</p>
          )}
        </div>
      )}

      <div className="sk-camera-detail__actions">
        <Link to={`/projects/${projectId}/analysis`} className="sk-button">
          Проанализировать новый снимок
        </Link>
        {camera.stream_url && (
          <a href={camera.stream_url} target="_blank" rel="noreferrer" className="sk-button sk-button--secondary">
            Смотреть трансляцию
          </a>
        )}
      </div>

      <div className="sk-panel" style={{ marginTop: "var(--sk-space-5)" }}>
        <h2>История снимков</h2>
        {history.length === 0 ? (
          <p className="sk-empty-state">Для этой камеры ещё нет сохранённых наблюдений.</p>
        ) : (
          <div className="sk-cameras-grid">
            {history.map((obs, index) => (
              <button
                key={obs.observation_id}
                type="button"
                className={`sk-camera-tile sk-camera-tile--static${index === historyIndex ? " sk-camera-tile--selected" : ""}`}
                onClick={() => setHistoryIndex(index)}
              >
                <div className="sk-camera-tile__media">
                  <img className="sk-camera-tile__img" src={getObservationImageUrl(projectId, obs.observation_id)} crossOrigin="use-credentials" alt="Сохранённый снимок" />
                </div>
                <div className="sk-camera-tile__footer">
                  <span className="sk-camera-tile__time">{new Date(obs.created_at).toLocaleString("ru-RU")}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
