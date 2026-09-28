import L from "leaflet";
import { MapContainer, Marker, TileLayer } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "./ProjectMiniMap.css";

interface ProjectMiniMapProps {
  latitude: number | null;
  longitude: number | null;
}

// Стандартные PNG-иконки Leaflet ломаются при сборке Vite (пути ресурсов не
// разрешаются) — тот же divIcon-подход, что и для маркеров камер на MapPage.
const projectPointIcon = L.divIcon({
  className: "sk-project-minimap-marker",
  html: '<span></span>',
  iconSize: [14, 14],
});

/**
 * Использует те же Leaflet/OpenStreetMap тайлы, что и основная карта площадки
 * (см. MapPage.tsx) — без нового провайдера карт. Список карточек не должен
 * запускать отдельные тяжёлые запросы сводки/погоды на карточку (см. план) —
 * этот компонент рисует только точку из уже загруженной карточки проекта.
 */
export function ProjectMiniMap({ latitude, longitude }: ProjectMiniMapProps) {
  if (latitude === null || longitude === null) {
    return (
      <div className="sk-project-minimap sk-project-minimap--empty" aria-hidden="true">
        Местоположение не указано
      </div>
    );
  }

  return (
    <div className="sk-project-minimap">
      <MapContainer
        center={[latitude, longitude]}
        zoom={13}
        zoomControl={false}
        dragging={false}
        scrollWheelZoom={false}
        doubleClickZoom={false}
        attributionControl={false}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <Marker position={[latitude, longitude]} icon={projectPointIcon} />
      </MapContainer>
    </div>
  );
}
