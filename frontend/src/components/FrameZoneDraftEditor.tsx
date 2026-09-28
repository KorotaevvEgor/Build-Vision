import { useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import type { DraftFrameZone, FrameZoneKind } from "../api";
import "./FrameZoneDraftEditor.css";

/** Соответствует `FrameZone.Kind` в core/models.py — справочника с сервера здесь ещё нет: проекта пока не существует. */
const KIND_LABELS: Record<FrameZoneKind, string> = {
  work: "Рабочая зона",
  parking: "Зона простоя (стоянка и отстой техники)",
  entrance: "Въезд и выезд",
  danger: "Опасная зона",
  uncontrolled: "Вне контроля",
};

const ZONE_COLORS: Record<FrameZoneKind, string> = {
  work: "#34d399",
  parking: "#f59e0b",
  entrance: "#60a5fa",
  danger: "#f87171",
  uncontrolled: "#93a1bd",
};

/** Меньше трёх точек не образуют многоугольник — то же ограничение стоит на сервере. */
const MIN_POINTS = 3;

type Point = [number, number];

function pointsAttribute(polygon: Point[]): string {
  return polygon.map(([x, y]) => `${x},${y}`).join(" ");
}

interface ImageSize {
  width: number;
  height: number;
}

interface FrameZoneDraftEditorProps {
  imageUrl: string;
  zones: DraftFrameZone[];
  onZonesChange: (zones: DraftFrameZone[]) => void;
  onImageSize?: (size: ImageSize) => void;
}

/**
 * Разметка зон работы/простоя на локальном превью фото (ещё не загруженном на
 * сервер) — на шаге создания проекта. По мотивам ZoneEditorPage.tsx, но без
 * сетевых вызовов: рисование идёт поверх обычного <img>, а результат хранится
 * в состоянии родителя и отправляется вместе с формой при финальной отправке.
 */
export function FrameZoneDraftEditor({
  imageUrl,
  zones,
  onZonesChange,
  onImageSize,
}: FrameZoneDraftEditorProps) {
  const [draft, setDraft] = useState<Point[]>([]);
  const [imageSize, setImageSize] = useState<ImageSize | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  const toFrameCoordinates = (event: ReactMouseEvent<SVGSVGElement>): Point | null => {
    const image = imageRef.current;
    if (!image || !imageSize) return null;
    const rect = image.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    const x = ((event.clientX - rect.left) / rect.width) * imageSize.width;
    const y = ((event.clientY - rect.top) / rect.height) * imageSize.height;
    return [Math.round(x), Math.round(y)];
  };

  const addPoint = (event: ReactMouseEvent<SVGSVGElement>) => {
    const point = toFrameCoordinates(event);
    if (!point) return;
    setDraft((current) => [...current, point]);
  };

  const finishDraft = (kind: FrameZoneKind) => {
    if (draft.length < MIN_POINTS) return;
    onZonesChange([
      ...zones,
      { name: `Зона ${zones.length + 1}`, kind, polygon: draft, note: "" },
    ]);
    setDraft([]);
  };

  const updateZone = (index: number, patch: Partial<DraftFrameZone>) => {
    onZonesChange(zones.map((zone, i) => (i === index ? { ...zone, ...patch } : zone)));
  };

  const removeZone = (index: number) => {
    onZonesChange(zones.filter((_, i) => i !== index));
  };

  return (
    <div className="sk-frame-zone-draft">
      <div className="sk-frame-zone-draft__frame">
        <img
          ref={imageRef}
          className="sk-frame-zone-draft__image"
          src={imageUrl}
          alt="Опорное фото для разметки зон"
          onLoad={(event) => {
            const size = {
              width: event.currentTarget.naturalWidth,
              height: event.currentTarget.naturalHeight,
            };
            setImageSize(size);
            onImageSize?.(size);
          }}
        />
        {imageSize && (
          <svg
            className="sk-frame-zone-draft__overlay"
            viewBox={`0 0 ${imageSize.width} ${imageSize.height}`}
            preserveAspectRatio="none"
            onClick={addPoint}
          >
            {zones.map((zone, index) => (
              <g key={`zone-${index}`} style={{ color: ZONE_COLORS[zone.kind] }}>
                <polygon className="sk-frame-zone-draft__polygon" points={pointsAttribute(zone.polygon)} />
                <text
                  className="sk-frame-zone-draft__label"
                  x={zone.polygon[0]?.[0] ?? 0}
                  y={(zone.polygon[0]?.[1] ?? 0) - 10}
                >
                  {zone.name}
                </text>
              </g>
            ))}

            {draft.length > 0 && (
              <g className="sk-frame-zone-draft__draft">
                <polyline className="sk-frame-zone-draft__draft-line" points={pointsAttribute(draft)} />
                {draft.map(([x, y], index) => (
                  <circle key={`${x}-${y}-${index}`} className="sk-frame-zone-draft__vertex" cx={x} cy={y} r={7} />
                ))}
              </g>
            )}
          </svg>
        )}
      </div>

      <div className="sk-frame-zone-draft__toolbar">
        <span className="sk-table__muted">
          {draft.length === 0
            ? "Кликайте по фото, чтобы обвести зону"
            : `Точек поставлено: ${draft.length}`}
        </span>
        <button
          type="button"
          className="sk-button"
          disabled={draft.length < MIN_POINTS}
          onClick={() => finishDraft("work")}
        >
          Замкнуть как зону работы
        </button>
        <button
          type="button"
          className="sk-button sk-button--secondary"
          disabled={draft.length < MIN_POINTS}
          onClick={() => finishDraft("parking")}
        >
          Замкнуть как зону простоя
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

      {zones.length > 0 && (
        <div className="sk-frame-zone-draft__list">
          {zones.map((zone, index) => (
            <div key={`zone-item-${index}`} className="sk-zone-item">
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
                  onChange={(event) => updateZone(index, { name: event.target.value })}
                />
                <select
                  aria-label="Тип зоны"
                  value={zone.kind}
                  onChange={(event) => updateZone(index, { kind: event.target.value as FrameZoneKind })}
                >
                  {Object.entries(KIND_LABELS).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
                <span className="sk-zone-item__meta">Точек: {zone.polygon.length}</span>
              </div>
              <button type="button" className="sk-button sk-button--secondary" onClick={() => removeZone(index)}>
                Удалить
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
