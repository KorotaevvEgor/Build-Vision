import { useState } from "react";
import { MapContainer, Marker, Polygon, Tooltip, TileLayer, useMapEvents } from "react-leaflet";
import L from "leaflet";
import type { DraftCamera } from "../api";
import { MapLayerToggle } from "./MapLayerToggle";
import { tileUrlFor, type MapLayerKind } from "../mapTiles";
import "leaflet/dist/leaflet.css";
import "./CameraFleetMap.css";

const cameraIcon = L.divIcon({
  className: "sk-camera-fleet-marker",
  html: "<span></span>",
  iconSize: [16, 16],
});

const cameraIconActive = L.divIcon({
  className: "sk-camera-fleet-marker sk-camera-fleet-marker--active",
  html: "<span></span>",
  iconSize: [20, 20],
});

const DEFAULT_CENTER: [number, number] = [55.7558, 37.6173];

interface ClickHandlerProps {
  onMapClick: (lat: number, lon: number) => void;
}

function ClickHandler({ onMapClick }: ClickHandlerProps) {
  useMapEvents({
    click(event) {
      onMapClick(event.latlng.lat, event.latlng.lng);
    },
  });
  return null;
}

interface CameraFleetMapProps {
  latitude: number | null;
  longitude: number | null;
  /** Граница площадки для ориентира — рисуется как read-only контур, без возможности править. */
  boundary: [number, number][];
  cameras: DraftCamera[];
  activeCameraId: string | null;
  onCameraPositionChange: (id: string, lat: number, lon: number) => void;
}

/**
 * Карта шага «Камеры и трансляции»: клик по карте назначает координаты той камере,
 * что сейчас выбрана как активная (см. CreateProjectPage). Граница площадки показана
 * только для ориентира и не редактируется — за это отвечает SiteBoundaryMap на шаге 1.
 */
export function CameraFleetMap({
  latitude,
  longitude,
  boundary,
  cameras,
  activeCameraId,
  onCameraPositionChange,
}: CameraFleetMapProps) {
  const [mapLayer, setMapLayer] = useState<MapLayerKind>("street");

  const placedCameras = cameras.filter((c) => c.latitude !== null && c.longitude !== null);
  const center: [number, number] =
    latitude !== null && longitude !== null
      ? [latitude, longitude]
      : placedCameras.length > 0
        ? [placedCameras[0].latitude as number, placedCameras[0].longitude as number]
        : boundary.length > 0
          ? [boundary[0][1], boundary[0][0]]
          : DEFAULT_CENTER;

  const boundaryPositions = boundary.map(([lon, lat]) => [lat, lon] as [number, number]);

  return (
    <div className="sk-camera-fleet-map">
      <MapLayerToggle value={mapLayer} onChange={setMapLayer} />
      <MapContainer center={center} zoom={16} attributionControl={false} style={{ height: "380px", borderRadius: "inherit" }}>
        <TileLayer url={tileUrlFor(mapLayer)} />
        <ClickHandler
          onMapClick={(lat, lon) => {
            if (activeCameraId) onCameraPositionChange(activeCameraId, lat, lon);
          }}
        />
        {boundaryPositions.length >= 3 && (
          <Polygon
            positions={boundaryPositions}
            pathOptions={{ color: "#34d399", dashArray: "6 4", fillOpacity: 0.08, weight: 2 }}
            interactive={false}
          />
        )}
        {placedCameras.map((cam) => (
          <Marker
            key={cam.id}
            position={[cam.latitude as number, cam.longitude as number]}
            icon={cam.id === activeCameraId ? cameraIconActive : cameraIcon}
          >
            <Tooltip>{cam.name || "Камера"}</Tooltip>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
