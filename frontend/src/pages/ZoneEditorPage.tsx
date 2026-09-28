import { useCallback, useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { useProject } from "../ProjectContext";
import {
  cameraReferenceImageUrl,
  fetchFrameZones,
  saveFrameZones,
  type FrameZone,
  type FrameZoneKind,
  type FrameZonesResponse,
} from "../api";
import "./ZoneEditorPage.css";

/**
 * Цвет по типу зоны: один и тот же для контура, заливки и подписи, чтобы
 * назначение зоны читалось с кадра без обращения к легенде.
 */
const ZONE_COLORS: Record<FrameZoneKind, string> = {
  work: "var(--sk-status-ok)",
  parking: "var(--sk-accent-strong)",
  entrance: "var(--sk-class-truck)",
  danger: "var(--sk-status-danger)",
  uncontrolled: "var(--sk-text-faint)",
};

/** Меньше трёх точек не образуют многоугольник — то же ограничение стоит на сервере. */
const MIN_POINTS = 3;

interface ImageSize {
  width: number;
  height: number;
}

type Point = [number, number];

function pointsAttribute(polygon: Point[]): string {
  return polygon.map(([x, y]) => `${x},${y}`).join(" ");
}

export function ZoneEditorPage() {
  const { projectId } = useProject();
  const { cameraId = "" } = useParams<{ cameraId: string }>();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [data, setData] = useState<FrameZonesResponse | null>(null);
  const [zones, setZones] = useState<FrameZone[]>([]);
  const [draft, setDraft] = useState<Point[]>([]);
  const [imageSize, setImageSize] = useState<ImageSize | null>(null);
  const [imageError, setImageError] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const imageRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    if (!cameraId) return;
    let cancelled = false;
    setError(null);
    fetchFrameZones(projectId, cameraId)
      .then((response) => {
        if (cancelled) return;
        setData(response);
        setZones(response.zones);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, cameraId]);

  // Зоны могли быть размечены по кадру другого разрешения (камеру перенастроили,
  // сменили поток). Пересчитываем их под текущий опорный кадр, иначе полигоны
  // легли бы мимо объектов, а сохранение закрепило бы ошибку.
  useEffect(() => {
    if (!imageSize) return;
    setZones((current) =>
      current.map((zone) => {
        const refWidth = zone.reference_width ?? imageSize.width;
        const refHeight = zone.reference_height ?? imageSize.height;
        if (refWidth === imageSize.width && refHeight === imageSize.height) return zone;
        const scaleX = imageSize.width / refWidth;
        const scaleY = imageSize.height / refHeight;
        return {
          ...zone,
          polygon: zone.polygon.map(
            ([x, y]) => [Math.round(x * scaleX), Math.round(y * scaleY)] as Point,
          ),
          reference_width: imageSize.width,
          reference_height: imageSize.height,
        };
      }),
    );
  }, [imageSize, data]);

  /**
   * Переводит клик в координаты опорного кадра.
   * Картинка растянута под ширину панели, поэтому экранные координаты хранить
   * нельзя: при другом размере окна зона уехала бы относительно объектов.
   */
  const toFrameCoordinates = useCallback(
    (event: ReactMouseEvent<SVGSVGElement>): Point | null => {
      const image = imageRef.current;
      if (!image || !imageSize) return null;
      const rect = image.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return null;
      const x = ((event.clientX - rect.left) / rect.width) * imageSize.width;
      const y = ((event.clientY - rect.top) / rect.height) * imageSize.height;
      return [Math.round(x), Math.round(y)];
    },
    [imageSize],
  );

  const addPoint = (event: ReactMouseEvent<SVGSVGElement>) => {
    if (!isAdmin) return;
    const point = toFrameCoordinates(event);
    if (!point) return;
    setDraft((current) => [...current, point]);
  };

  const finishDraft = () => {
    if (draft.length < MIN_POINTS || !imageSize) return;
    setZones((current) => [
      ...current,
      {
        name: `Зона ${current.length + 1}`,
        kind: "work",
        polygon: draft,
        reference_width: imageSize.width,
        reference_height: imageSize.height,
        stage_id: null,
        note: "",
      },
    ]);
    setDraft([]);
    setSavedAt(null);
  };

  const updateZone = (index: number, patch: Partial<FrameZone>) => {
    setZones((current) => current.map((zone, i) => (i === index ? { ...zone, ...patch } : zone)));
    setSavedAt(null);
  };

  const removeZone = (index: number) => {
    setZones((current) => current.filter((_, i) => i !== index));
    setSavedAt(null);
  };

  const save = async () => {
    if (!imageSize) return;
    setSaving(true);
    setError(null);
    try {
      const response = await saveFrameZones(projectId, cameraId, {
        reference_width: imageSize.width,
        reference_height: imageSize.height,
        zones,
      });
      setZones(response.zones);
      setSavedAt(new Date().toLocaleTimeString("ru-RU"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить зоны");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="sk-zone-editor">
      <Link to={`/projects/${projectId}/cameras/${cameraId}`} className="sk-zone-editor__back">
        ← Камера
      </Link>
      <h1>Зоны на кадре</h1>
      <p className="sk-table__muted">
        {data ? `${data.camera_name} · участок ${data.zone_id}` : "Загрузка…"}
      </p>
      <p className="sk-zone-editor__intro">
        Разметка зон отличает работу от простоя: экскаватор в котловане и тот же экскаватор на
        стоянке означают разное. Обведите рабочие участки, места отстоя техники, въезд, опасные
        зоны и участки, которые камеры не просматривают.
      </p>

      {error && <div className="sk-panel sk-panel--error">{error}</div>}

      <div className="sk-zone-editor__grid">
        <div className="sk-panel sk-zone-editor__canvas">
          {imageError ? (
            <p className="sk-empty-state">
              У камеры ещё нет ни одного снимка. Загрузите кадр на экране анализа, указав эту
              камеру, — по нему и размечаются зоны.
            </p>
          ) : (
            <>
              <div className="sk-zone-editor__frame">
                <img
                  ref={imageRef}
                  className="sk-zone-editor__image"
                  src={cameraReferenceImageUrl(projectId, cameraId)}
                  crossOrigin="use-credentials"
                  alt="Опорный кадр камеры"
                  onLoad={(event) =>
                    setImageSize({
                      width: event.currentTarget.naturalWidth,
                      height: event.currentTarget.naturalHeight,
                    })
                  }
                  onError={() => setImageError(true)}
                />
                {imageSize && (
                  <svg
                    className="sk-zone-editor__overlay"
                    viewBox={`0 0 ${imageSize.width} ${imageSize.height}`}
                    preserveAspectRatio="none"
                    onClick={addPoint}
                  >
                    {zones.map((zone, index) => (
                      <g key={zone.id ?? `zone-${index}`} style={{ color: ZONE_COLORS[zone.kind] }}>
                        <polygon
                          className="sk-zone-editor__polygon"
                          points={pointsAttribute(zone.polygon)}
                        />
                        <text
                          className="sk-zone-editor__label"
                          x={zone.polygon[0]?.[0] ?? 0}
                          y={(zone.polygon[0]?.[1] ?? 0) - 10}
                        >
                          {zone.name}
                        </text>
                      </g>
                    ))}

                    {draft.length > 0 && (
                      <g className="sk-zone-editor__draft">
                        <polyline
                          className="sk-zone-editor__draft-line"
                          points={pointsAttribute(draft)}
                        />
                        {draft.map(([x, y], index) => (
                          <circle
                            key={`${x}-${y}-${index}`}
                            className="sk-zone-editor__vertex"
                            cx={x}
                            cy={y}
                            r={7}
                          />
                        ))}
                      </g>
                    )}
                  </svg>
                )}
              </div>

              {isAdmin && (
                <div className="sk-zone-editor__toolbar">
                  <span className="sk-table__muted">
                    {draft.length === 0
                      ? "Кликайте по кадру, чтобы обвести зону"
                      : `Точек поставлено: ${draft.length}`}
                  </span>
                  <button
                    type="button"
                    className="sk-button"
                    disabled={draft.length < MIN_POINTS}
                    onClick={finishDraft}
                  >
                    Замкнуть зону
                  </button>
                  <button
                    type="button"
                    className="sk-button sk-button--secondary"
                    disabled={draft.length === 0}
                    onClick={() => setDraft((current) => current.slice(0, -1))}
                  >
                    Убрать точку
                  </button>
                  <button
                    type="button"
                    className="sk-button sk-button--secondary"
                    disabled={draft.length === 0}
                    onClick={() => setDraft([])}
                  >
                    Сбросить
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        <div className="sk-panel sk-zone-editor__list">
          <h2>Размеченные зоны</h2>
          {zones.length === 0 && <p className="sk-empty-state">Зон пока нет.</p>}

          {zones.map((zone, index) => (
            <div key={zone.id ?? `new-${index}`} className="sk-zone-item">
              <span
                className="sk-zone-item__swatch"
                style={{ background: ZONE_COLORS[zone.kind] }}
                aria-hidden="true"
              />
              <div className="sk-zone-item__fields">
                <input
                  type="text"
                  aria-label="Название зоны"
                  value={zone.name}
                  disabled={!isAdmin}
                  onChange={(event) => updateZone(index, { name: event.target.value })}
                />
                <select
                  aria-label="Тип зоны"
                  value={zone.kind}
                  disabled={!isAdmin}
                  onChange={(event) =>
                    updateZone(index, { kind: event.target.value as FrameZoneKind })
                  }
                >
                  {data?.kinds.map((kind) => (
                    <option key={kind.key} value={kind.key}>
                      {kind.label_ru}
                    </option>
                  ))}
                </select>
                {zone.kind === "work" && (
                  <select
                    aria-label="Этап графика"
                    value={zone.stage_id ?? ""}
                    disabled={!isAdmin}
                    onChange={(event) =>
                      updateZone(index, { stage_id: event.target.value || null })
                    }
                  >
                    <option value="">Этап не указан</option>
                    {data?.stages.map((stage) => (
                      <option key={stage.stage_id} value={stage.stage_id}>
                        {stage.work_name}
                      </option>
                    ))}
                  </select>
                )}
                <span className="sk-zone-item__meta">Точек: {zone.polygon.length}</span>
              </div>
              {isAdmin && (
                <button
                  type="button"
                  className="sk-button sk-button--secondary"
                  onClick={() => removeZone(index)}
                >
                  Удалить
                </button>
              )}
            </div>
          ))}

          {isAdmin ? (
            <div className="sk-zone-editor__actions">
              <button
                type="button"
                className="sk-button"
                disabled={saving || !imageSize}
                onClick={() => void save()}
              >
                {saving ? "Сохраняем…" : "Сохранить зоны"}
              </button>
              {savedAt && <span className="sk-zone-editor__saved">Сохранено в {savedAt}</span>}
            </div>
          ) : (
            <p className="sk-table__muted">Изменять разметку может только администратор.</p>
          )}
        </div>
      </div>
    </div>
  );
}
