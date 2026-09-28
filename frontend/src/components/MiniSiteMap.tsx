import { useEffect } from "react";
import { GeoJSON, MapContainer, Marker, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import type { Feature, FeatureCollection } from "geojson";
import type { DeviationStatus } from "../api";
import { STREET_TILE_URL } from "../mapTiles";
import "leaflet/dist/leaflet.css";
import "./MiniSiteMap.css";

const STATUS_COLOR: Record<DeviationStatus, string> = {
  no_deviation: "#34d399",
  possible_deviation: "#f87171",
  insufficient_data: "#93a1bd",
};
const NO_DATA_COLOR = "#647190";

function cameraIcon() {
  return L.divIcon({ className: "sk-mini-site-map__camera", html: "<span></span>", iconSize: [10, 10] });
}

/**
 * Карточка на Главной не имеет фиксированной высоты (растягивается по сетке),
 * поэтому зум по числу недостаточен — граница площадки может не влезать
 * целиком. Считаем bounds по реальной геометрии и подгоняем вид под них,
 * включая пересчёт при изменении размера контейнера (flex/грид ещё не
 * стабилизировались на момент монтирования карты).
 */
function FitBounds({ bounds }: { bounds: L.LatLngBounds | null }) {
  const map = useMap();

  useEffect(() => {
    if (bounds && bounds.isValid()) {
      map.fitBounds(bounds, { padding: [18, 18] });
    }
  }, [map, bounds]);

  useEffect(() => {
    const container = map.getContainer();
    const observer = new ResizeObserver(() => {
      map.invalidateSize();
      if (bounds && bounds.isValid()) {
        map.fitBounds(bounds, { padding: [18, 18] });
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [map, bounds]);

  return null;
}

interface MiniSiteMapProps {
  /** Все фичи площадки (границы, зоны, камеры) — как в SiteResponse.geojson.features. */
  features: Feature[];
  /** Статус последнего наблюдения по зоне — для той же раскраски, что и на большой карте. */
  zoneStatus: (zoneId: string) => DeviationStatus | undefined;
  center: [number, number] | null;
}

/**
 * Уменьшенная некликабельная копия карты площадки для карточки на главной —
 * только просмотр, без выбора зон и переключения слоёв (это есть на /map).
 * Наклон через CSS-transform — декоративный эффект по просьбе заказчика,
 * убирается при наведении, чтобы можно было спокойно рассмотреть карту.
 */
export function MiniSiteMap({ features, zoneStatus, center }: MiniSiteMapProps) {
  if (!center) {
    return <div className="sk-mini-site-map sk-mini-site-map--empty">Нет геометрии площадки</div>;
  }

  const polygonFeatures: FeatureCollection = {
    type: "FeatureCollection",
    features: features.filter((f) => f.properties?.kind !== "camera"),
  };
  const cameraFeatures = features.filter((f) => f.properties?.kind === "camera");

  let bounds: L.LatLngBounds | null = null;
  if (polygonFeatures.features.length > 0) {
    try {
      const computed = L.geoJSON(polygonFeatures as GeoJSON.GeoJsonObject).getBounds();
      if (computed.isValid()) bounds = computed;
    } catch {
      bounds = null;
    }
  }

  return (
    <div className="sk-mini-site-map">
      <div className="sk-mini-site-map__flat">
        <MapContainer
          center={center}
          zoom={17}
          zoomControl={false}
          dragging={false}
          scrollWheelZoom={false}
          doubleClickZoom={false}
          touchZoom={false}
          boxZoom={false}
          keyboard={false}
          attributionControl={false}
          style={{ height: "100%", width: "100%" }}
        >
          <FitBounds bounds={bounds} />
          <TileLayer url={STREET_TILE_URL} />
          <GeoJSON
            data={polygonFeatures}
            style={(feature) => {
              if (feature?.properties?.kind !== "zone") {
                return { color: NO_DATA_COLOR, weight: 1, fillOpacity: 0.03 };
              }
              const status = zoneStatus(feature.properties?.id);
              const color = status ? STATUS_COLOR[status] : NO_DATA_COLOR;
              return { color, weight: 1.5, fillColor: color, fillOpacity: 0.2 };
            }}
          />
          {cameraFeatures.map((feature) => {
            if (feature.geometry.type !== "Point") return null;
            const [lon, lat] = feature.geometry.coordinates;
            return <Marker key={feature.properties?.id} position={[lat, lon]} icon={cameraIcon()} />;
          })}
        </MapContainer>
      </div>
    </div>
  );
}
