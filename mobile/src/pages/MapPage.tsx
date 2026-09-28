import { useEffect, useMemo, useState } from "react";
import { GeoJSON, MapContainer, TileLayer } from "react-leaflet";
import type { FeatureCollection } from "geojson";
import { fetchSite, type SiteResponse } from "../api";
import { useProject } from "../ProjectContext";
import "leaflet/dist/leaflet.css";
import "./MapPage.css";

export function MapPage() {
  const { projectId, project } = useProject();
  const [site, setSite] = useState<SiteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSite(null);
    setError(null);
    fetchSite(projectId)
      .then((data) => {
        if (!cancelled) setSite(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const polygonFeatures = useMemo<FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: (site?.geojson.features ?? []).filter((f) => f.properties?.kind !== "camera"),
    }),
    [site],
  );

  const boundaryFeature = site?.geojson.features.find((f) => f.properties?.kind === "site_boundary");
  const mapCenter = useMemo<[number, number] | null>(() => {
    if (boundaryFeature && boundaryFeature.geometry.type === "Polygon") {
      const ring = boundaryFeature.geometry.coordinates[0];
      const lats = ring.map(([, lat]) => lat);
      const lons = ring.map(([lon]) => lon);
      return [lats.reduce((a, b) => a + b, 0) / lats.length, lons.reduce((a, b) => a + b, 0) / lons.length];
    }
    if (project.latitude !== null && project.longitude !== null) {
      return [project.latitude, project.longitude];
    }
    return null;
  }, [boundaryFeature, project.latitude, project.longitude]);

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить карту: {error}</div>;
  }
  if (!site) {
    return <div className="sk-panel">Загрузка карты…</div>;
  }
  if (!mapCenter) {
    return (
      <div>
        <h1>Карта площадки</h1>
        <div className="sk-panel">
          <p className="sk-empty-state">У проекта ещё не заданы граница или точка на карте.</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1>Карта площадки</h1>
      <div className="sk-mobile-map">
        <MapContainer key={projectId} center={mapCenter} zoom={16} style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution='&copy; OpenStreetMap contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <GeoJSON data={polygonFeatures} style={{ color: "#3b82f6", weight: 1.5, fillOpacity: 0.15 }} />
        </MapContainer>
      </div>
      {site.schedule_is_demo && (
        <p className="sk-demo-note">Координаты площадки — демонстрационные, не привязаны к реальному объекту.</p>
      )}
    </div>
  );
}
