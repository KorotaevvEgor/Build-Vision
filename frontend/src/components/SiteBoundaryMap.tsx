import { useCallback, useState } from "react";
import { MapContainer, Marker, Polygon, Polyline, TileLayer, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { MapLayerToggle } from "./MapLayerToggle";
import { tileUrlFor, type MapLayerKind } from "../mapTiles";
import "leaflet/dist/leaflet.css";
import "./SiteBoundaryMap.css";

// Стандартные PNG-иконки Leaflet ломаются при сборке Vite (см. ProjectMiniMap.tsx) —
// тот же divIcon-подход, что и для точки проекта и маркеров камер на MapPage.
const pointIcon = L.divIcon({
  className: "sk-boundary-map-marker",
  html: "<span></span>",
  iconSize: [16, 16],
});

const vertexIcon = L.divIcon({
  className: "sk-boundary-map-vertex",
  html: "<span></span>",
  iconSize: [10, 10],
});

// Центр показа по умолчанию, пока у проекта нет ни точки, ни границы — без этого
// пришлось бы указывать произвольную демоплощадку как «настоящий» центр карты.
const DEFAULT_CENTER: [number, number] = [55.7558, 37.6173];

export type BoundaryMapMode = "point" | "boundary";

interface ClickHandlerProps {
  mode: BoundaryMapMode;
  onPointClick: (lat: number, lon: number) => void;
  onBoundaryClick: (lat: number, lon: number) => void;
}

function ClickHandler({ mode, onPointClick, onBoundaryClick }: ClickHandlerProps) {
  useMapEvents({
    click(event) {
      const { lat, lng } = event.latlng;
      if (mode === "boundary") onBoundaryClick(lat, lng);
      else onPointClick(lat, lng);
    },
  });
  return null;
}

interface SiteBoundaryMapProps {
  latitude: number | null;
  longitude: number | null;
  /** Точки границы в формате GeoJSON — [долгота, широта], по порядку обхода контура. */
  boundary: [number, number][];
  mode: BoundaryMapMode;
  onPointChange: (lat: number, lon: number) => void;
  onBoundaryChange: (points: [number, number][]) => void;
}

/**
 * Карта первого шага визарда создания проекта: точка проекта и граница площадки.
 * Режим переключается родителем (кнопки тулбара) — сама карта только рисует то,
 * что в неё передали, и сообщает о кликах через колбэки.
 */
export function SiteBoundaryMap({
  latitude,
  longitude,
  boundary,
  mode,
  onPointChange,
  onBoundaryChange,
}: SiteBoundaryMapProps) {
  const [mapLayer, setMapLayer] = useState<MapLayerKind>("street");

  const center: [number, number] =
    latitude !== null && longitude !== null
      ? [latitude, longitude]
      : boundary.length > 0
        ? [boundary[0][1], boundary[0][0]]
        : DEFAULT_CENTER;

  const addBoundaryPoint = useCallback(
    (lat: number, lon: number) => {
      onBoundaryChange([...boundary, [lon, lat]]);
    },
    [boundary, onBoundaryChange],
  );

  // Leaflet-координаты — [широта, долгота], в отличие от GeoJSON [долгота, широта].
  const positions = boundary.map(([lon, lat]) => [lat, lon] as [number, number]);

  return (
    <div className="sk-boundary-map">
      <MapLayerToggle value={mapLayer} onChange={setMapLayer} />
      <MapContainer
        center={center}
        zoom={15}
        attributionControl={false}
        style={{ height: "380px", borderRadius: "inherit" }}
      >
        <TileLayer url={tileUrlFor(mapLayer)} />
        <ClickHandler mode={mode} onPointClick={onPointChange} onBoundaryClick={addBoundaryPoint} />
        {latitude !== null && longitude !== null && (
          <Marker position={[latitude, longitude]} icon={pointIcon} />
        )}
        {positions.length >= 3 && <Polygon positions={positions} pathOptions={{ color: "#34d399" }} />}
        {positions.length > 0 && positions.length < 3 && (
          <Polyline positions={positions} pathOptions={{ color: "#34d399" }} />
        )}
        {positions.map(([lat, lon], index) => (
          <Marker key={`${lat}-${lon}-${index}`} position={[lat, lon]} icon={vertexIcon} />
        ))}
      </MapContainer>
    </div>
  );
}
