import type { MapLayerKind } from "../mapTiles";
import "./MapLayerToggle.css";

interface MapLayerToggleProps {
  value: MapLayerKind;
  onChange: (value: MapLayerKind) => void;
}

/**
 * Переключатель "Схема / Спутник", накладываемый поверх карты.
 * Рендерится как сосед <MapContainer>, а не внутри него — клики по кнопкам
 * не должны долетать до обработчика клика самой карты (см. SiteBoundaryMap).
 */
export function MapLayerToggle({ value, onChange }: MapLayerToggleProps) {
  return (
    <div className="sk-map-layer-toggle" role="group" aria-label="Слой карты">
      <button
        type="button"
        className={`sk-map-layer-toggle__btn${value === "street" ? " sk-map-layer-toggle__btn--active" : ""}`}
        onClick={() => onChange("street")}
      >
        Схема
      </button>
      <button
        type="button"
        className={`sk-map-layer-toggle__btn${value === "satellite" ? " sk-map-layer-toggle__btn--active" : ""}`}
        onClick={() => onChange("satellite")}
      >
        Спутник
      </button>
    </div>
  );
}
