import { useCallback, useEffect, useMemo, useState } from "react";
import { GeoJSON, MapContainer, Marker, Polygon, Polyline, Popup, TileLayer, Tooltip, useMapEvents } from "react-leaflet";
import L from "leaflet";
import type { Layer } from "leaflet";
import type { Feature, FeatureCollection } from "geojson";
import {
  createCamera,
  createZone,
  deleteCamera,
  deleteZone,
  fetchCameras,
  fetchDashboard,
  fetchSite,
  fetchZones,
  updateCamera,
  updateZone,
  type CameraSummary,
  type DashboardResponse,
  type DeviationStatus,
  type SiteResponse,
  type ZoneDetail,
  type ZoneKind,
  type ZoneKindChoice,
} from "../api";
import { useAuth } from "../AuthContext";
import { useProject } from "../ProjectContext";
import { MapLayerToggle } from "../components/MapLayerToggle";
import { tileUrlFor, type MapLayerKind } from "../mapTiles";
import "leaflet/dist/leaflet.css";
import "./MapPage.css";

const STATUS_COLOR: Record<DeviationStatus, string> = {
  no_deviation: "#34d399",
  possible_deviation: "#f87171",
  insufficient_data: "#93a1bd",
};
const NO_DATA_COLOR = "#647190";

const ZONE_KIND_COLOR: Record<ZoneKind, string> = {
  work: "#34d399",
  parking: "#60a5fa",
  entrance: "#fbbf24",
  danger: "#f87171",
  uncontrolled: "#94a3b8",
};

function cameraIcon(color: string) {
  return L.divIcon({
    className: "sk-camera-marker",
    html: `<span style="background:${color}"></span>`,
    iconSize: [16, 16],
  });
}

const vertexIcon = L.divIcon({
  className: "sk-map-vertex-marker",
  html: "<span></span>",
  iconSize: [10, 10],
});

/** [долгота, широта] (GeoJSON) -> [широта, долгота] (Leaflet), без замыкающей точки контура. */
function polygonToLatLngs(geometry: GeoJSON.Polygon): [number, number][] {
  const ring = geometry.coordinates[0] ?? [];
  const points = ring.map(([lon, lat]) => [lat, lon] as [number, number]);
  if (
    points.length > 1 &&
    points[0][0] === points[points.length - 1][0] &&
    points[0][1] === points[points.length - 1][1]
  ) {
    return points.slice(0, -1);
  }
  return points;
}

type EditTool = "none" | "draw-zone" | "place-camera";

interface EditClickHandlerProps {
  active: boolean;
  onClick: (lat: number, lon: number) => void;
}

/** Активен только пока выбран инструмент рисования/размещения — иначе клики по карте ничего не делают. */
function EditClickHandler({ active, onClick }: EditClickHandlerProps) {
  useMapEvents({
    click(event) {
      if (active) onClick(event.latlng.lat, event.latlng.lng);
    },
  });
  return null;
}

export function MapPage() {
  const { user } = useAuth();
  const { projectId, project } = useProject();
  const isAdmin = user?.role === "admin";
  const [site, setSite] = useState<SiteResponse | null>(null);
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [mapLayer, setMapLayer] = useState<MapLayerKind>("street");

  // --- Режим редактирования (только администратор): зоны и камеры площадки ---
  const [editMode, setEditMode] = useState(false);
  const [zones, setZones] = useState<ZoneDetail[] | null>(null);
  const [zoneKinds, setZoneKinds] = useState<ZoneKindChoice[]>([]);
  const [cameras, setCameras] = useState<CameraSummary[] | null>(null);
  const [editLoadError, setEditLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [tool, setTool] = useState<EditTool>("none");
  const [draftPoints, setDraftPoints] = useState<[number, number][]>([]);
  const [drawingZoneId, setDrawingZoneId] = useState<string | null>(null);
  const [zoneFormOpen, setZoneFormOpen] = useState(false);
  const [zoneForm, setZoneForm] = useState<{ name: string; kind: ZoneKind }>({ name: "", kind: "work" });

  const [pendingCameraPoint, setPendingCameraPoint] = useState<{ lat: number; lon: number } | null>(null);
  const [cameraForm, setCameraForm] = useState<{ name: string; stream_url: string; zone_id: string }>({
    name: "",
    stream_url: "",
    zone_id: "",
  });

  const [editingZoneId, setEditingZoneId] = useState<string | null>(null);
  const [zoneMetaForm, setZoneMetaForm] = useState<{ name: string; kind: ZoneKind }>({ name: "", kind: "work" });
  const [pendingDeleteZoneId, setPendingDeleteZoneId] = useState<string | null>(null);

  const [editingCameraId, setEditingCameraId] = useState<string | null>(null);
  const [cameraEditForm, setCameraEditForm] = useState<{ name: string; stream_url: string; zone_id: string }>({
    name: "",
    stream_url: "",
    zone_id: "",
  });
  const [pendingDeleteCameraId, setPendingDeleteCameraId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSite(null);
    setDashboard(null);
    setError(null);
    setSelectedZoneId(null);
    Promise.all([fetchSite(projectId), fetchDashboard(projectId)])
      .then(([s, d]) => {
        if (cancelled) return;
        setSite(s);
        setDashboard(d);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const reloadEditableData = useCallback(async () => {
    const [zonesRes, camerasRes, siteRes] = await Promise.all([
      fetchZones(projectId),
      fetchCameras(projectId),
      fetchSite(projectId),
    ]);
    setZones(zonesRes.zones);
    setZoneKinds(zonesRes.kinds);
    setCameras(camerasRes.cameras);
    setSite(siteRes);
  }, [projectId]);

  useEffect(() => {
    if (!editMode || !isAdmin) return;
    let cancelled = false;
    setEditLoadError(null);
    fetchZones(projectId)
      .then((zonesRes) => {
        if (cancelled) return;
        setZones(zonesRes.zones);
        setZoneKinds(zonesRes.kinds);
        return fetchCameras(projectId);
      })
      .then((camerasRes) => {
        if (cancelled || !camerasRes) return;
        setCameras(camerasRes.cameras);
      })
      .catch((err: Error) => {
        if (!cancelled) setEditLoadError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [editMode, isAdmin, projectId]);

  const resetDrawState = useCallback(() => {
    setTool("none");
    setDraftPoints([]);
    setDrawingZoneId(null);
    setZoneFormOpen(false);
    setPendingCameraPoint(null);
    setActionError(null);
  }, []);

  const toggleEditMode = () => {
    resetDrawState();
    setEditingZoneId(null);
    setEditingCameraId(null);
    setPendingDeleteZoneId(null);
    setPendingDeleteCameraId(null);
    setEditMode((v) => !v);
  };

  const startNewZone = () => {
    resetDrawState();
    setTool("draw-zone");
  };

  const startRedrawZone = (zone: ZoneDetail) => {
    resetDrawState();
    setDrawingZoneId(zone.zone_id);
    setTool("draw-zone");
    setDraftPoints(polygonToLatLngs(zone.geometry_geojson).map(([lat, lon]) => [lon, lat]));
  };

  const startPlaceCamera = () => {
    resetDrawState();
    setTool("place-camera");
  };

  const handleEditMapClick = (lat: number, lon: number) => {
    if (tool === "draw-zone") {
      setDraftPoints((pts) => [...pts, [lon, lat]]);
    } else if (tool === "place-camera") {
      setPendingCameraPoint({ lat, lon });
      setCameraForm({ name: "", stream_url: "", zone_id: (zones ?? [])[0]?.zone_id ?? "" });
    }
  };

  const undoLastDraftPoint = () => setDraftPoints((pts) => pts.slice(0, -1));

  const finishZoneDraw = () => {
    if (draftPoints.length < 3) return;
    const existing = drawingZoneId ? (zones ?? []).find((z) => z.zone_id === drawingZoneId) : null;
    setZoneForm(existing ? { name: existing.name, kind: existing.kind } : { name: "", kind: "work" });
    setZoneFormOpen(true);
  };

  const submitZoneForm = async () => {
    if (draftPoints.length < 3 || !zoneForm.name.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      if (drawingZoneId) {
        await updateZone(projectId, drawingZoneId, {
          name: zoneForm.name.trim(),
          kind: zoneForm.kind,
          points: draftPoints,
        });
      } else {
        await createZone(projectId, { name: zoneForm.name.trim(), kind: zoneForm.kind, points: draftPoints });
      }
      await reloadEditableData();
      resetDrawState();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не удалось сохранить зону");
    } finally {
      setBusy(false);
    }
  };

  const submitCameraForm = async () => {
    if (!pendingCameraPoint || !cameraForm.name.trim() || !cameraForm.zone_id) return;
    setBusy(true);
    setActionError(null);
    try {
      await createCamera(projectId, {
        name: cameraForm.name.trim(),
        zone_id: cameraForm.zone_id,
        latitude: pendingCameraPoint.lat,
        longitude: pendingCameraPoint.lon,
        stream_url: cameraForm.stream_url.trim(),
      });
      await reloadEditableData();
      resetDrawState();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не удалось создать камеру");
    } finally {
      setBusy(false);
    }
  };

  const startEditZoneMeta = (zone: ZoneDetail) => {
    setPendingDeleteZoneId(null);
    setEditingZoneId(zone.zone_id);
    setZoneMetaForm({ name: zone.name, kind: zone.kind });
  };

  const submitZoneMeta = async (zone: ZoneDetail) => {
    if (!zoneMetaForm.name.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      await updateZone(projectId, zone.zone_id, { name: zoneMetaForm.name.trim(), kind: zoneMetaForm.kind });
      await reloadEditableData();
      setEditingZoneId(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не удалось сохранить зону");
    } finally {
      setBusy(false);
    }
  };

  const confirmDeleteZone = async (zoneId: string) => {
    setBusy(true);
    setActionError(null);
    try {
      await deleteZone(projectId, zoneId);
      await reloadEditableData();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не удалось удалить зону");
    } finally {
      setBusy(false);
      setPendingDeleteZoneId(null);
    }
  };

  const startEditCamera = (cam: CameraSummary) => {
    setPendingDeleteCameraId(null);
    setEditingCameraId(cam.camera_id);
    setCameraEditForm({ name: cam.name, stream_url: cam.stream_url, zone_id: cam.zone_id });
  };

  const submitCameraEdit = async (cam: CameraSummary) => {
    if (!cameraEditForm.name.trim() || !cameraEditForm.zone_id) return;
    setBusy(true);
    setActionError(null);
    try {
      await updateCamera(projectId, cam.camera_id, {
        name: cameraEditForm.name.trim(),
        zone_id: cameraEditForm.zone_id,
        latitude: cam.latitude,
        longitude: cam.longitude,
        stream_url: cameraEditForm.stream_url.trim(),
      });
      await reloadEditableData();
      setEditingCameraId(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не удалось сохранить камеру");
    } finally {
      setBusy(false);
    }
  };

  const handleCameraDragEnd = async (cam: CameraSummary, event: L.DragEndEvent) => {
    const marker = event.target as L.Marker;
    const { lat, lng } = marker.getLatLng();
    setBusy(true);
    setActionError(null);
    try {
      await updateCamera(projectId, cam.camera_id, {
        name: cam.name,
        zone_id: cam.zone_id,
        latitude: lat,
        longitude: lng,
        stream_url: cam.stream_url,
      });
      await reloadEditableData();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не удалось переместить камеру");
      await reloadEditableData();
    } finally {
      setBusy(false);
    }
  };

  const confirmDeleteCamera = async (cameraId: string) => {
    setBusy(true);
    setActionError(null);
    try {
      await deleteCamera(projectId, cameraId);
      await reloadEditableData();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не удалось удалить камеру");
    } finally {
      setBusy(false);
      setPendingDeleteCameraId(null);
    }
  };

  const polygonFeatures = useMemo<FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: (site?.geojson.features ?? []).filter((f) => f.properties?.kind !== "camera"),
    }),
    [site],
  );
  const cameraFeatures = useMemo(
    () => (site?.geojson.features ?? []).filter((f) => f.properties?.kind === "camera"),
    [site],
  );

  // Карта пересоздаётся/позиционируется по геометрии выбранного проекта (см. план,
  // «Состояние клиентов и карты») — без жёстко зашитой московской демоплощадки.
  const boundaryFeature = site?.geojson.features.find((f) => f.properties?.kind === "site_boundary");
  const boundaryLatLngs = useMemo(
    () =>
      boundaryFeature && boundaryFeature.geometry.type === "Polygon"
        ? polygonToLatLngs(boundaryFeature.geometry)
        : null,
    [boundaryFeature],
  );
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
  if (!site || !dashboard) {
    return <div className="sk-panel">Загрузка карты…</div>;
  }
  if (!mapCenter) {
    return (
      <div className="sk-map-page">
        <header>
          <h1>Карта площадки</h1>
        </header>
        <div className="sk-panel" style={{ marginTop: "var(--sk-space-4)" }}>
          <p className="sk-empty-state">
            У проекта ещё не заданы граница или точка на карте — настройте их через Django admin.
          </p>
        </div>
      </div>
    );
  }

  const zoneStatus = (zoneId: string): DeviationStatus | undefined =>
    dashboard.zones.find((z) => z.zone_id === zoneId)?.latest_observation?.overall_status;

  const styleForFeature = (feature?: Feature) => {
    if (feature?.properties?.kind !== "zone") {
      return { color: NO_DATA_COLOR, weight: 1, fillOpacity: 0.02 };
    }
    const isSelected = feature.properties?.id === selectedZoneId;
    const status = zoneStatus(feature.properties?.id);
    const color = status ? STATUS_COLOR[status] : NO_DATA_COLOR;
    return {
      color,
      weight: isSelected ? 3 : 1.5,
      fillColor: color,
      fillOpacity: isSelected ? 0.3 : 0.15,
    };
  };

  const onEachFeature = (feature: Feature, layer: Layer) => {
    if (feature.properties?.kind !== "zone") return;
    layer.on("click", () => setSelectedZoneId(feature.properties?.id));
    layer.bindTooltip(feature.properties?.name ?? "Зона");
  };

  const drawing = tool !== "none";
  const draftLatLngs = draftPoints.map(([lon, lat]) => [lat, lon] as [number, number]);

  return (
    <div className="sk-map-page">
      <header className="sk-map-page__header">
        <div className="sk-map-page__header-row">
          <h1>Карта площадки</h1>
          {isAdmin && (
            <button type="button" className="sk-button sk-button--secondary" onClick={toggleEditMode}>
              {editMode ? "Завершить редактирование" : "Редактировать карту"}
            </button>
          )}
        </div>
        {site.schedule_is_demo && !editMode && (
          <p className="sk-demo-note">Координаты площадки и камер — демонстрационные, не привязаны к реальному объекту.</p>
        )}
      </header>

      <div className={editMode ? "sk-map-page__layout sk-map-page__layout--editing" : "sk-map-page__layout"}>
        <div className="sk-panel sk-map-page__map">
          <MapLayerToggle value={mapLayer} onChange={setMapLayer} />
          <MapContainer
            key={projectId}
            center={mapCenter}
            zoom={16}
            attributionControl={false}
            style={{ height: "540px", borderRadius: "inherit" }}
          >
            <TileLayer url={tileUrlFor(mapLayer)} />

            {editMode ? (
              <>
                <EditClickHandler active={drawing} onClick={handleEditMapClick} />

                {boundaryLatLngs && boundaryLatLngs.length >= 3 && (
                  <Polygon
                    positions={boundaryLatLngs}
                    pathOptions={{ color: NO_DATA_COLOR, weight: 1, dashArray: "6 4", fillOpacity: 0.02 }}
                    interactive={false}
                  />
                )}

                {(zones ?? [])
                  .filter((z) => z.zone_id !== drawingZoneId)
                  .map((zone) => {
                    const color = ZONE_KIND_COLOR[zone.kind] ?? NO_DATA_COLOR;
                    const selected = zone.zone_id === editingZoneId;
                    return (
                      <Polygon
                        key={zone.zone_id}
                        positions={polygonToLatLngs(zone.geometry_geojson)}
                        pathOptions={{
                          color,
                          weight: selected ? 3 : 1.5,
                          fillColor: color,
                          fillOpacity: selected ? 0.35 : 0.15,
                        }}
                        interactive={!drawing}
                        eventHandlers={{ click: () => startEditZoneMeta(zone) }}
                      >
                        <Tooltip>
                          {zone.name} · {zone.kind_label_ru}
                        </Tooltip>
                      </Polygon>
                    );
                  })}

                {draftLatLngs.length >= 3 && (
                  <Polygon positions={draftLatLngs} pathOptions={{ color: "#fbbf24", weight: 2, fillOpacity: 0.15 }} />
                )}
                {draftLatLngs.length > 0 && draftLatLngs.length < 3 && (
                  <Polyline positions={draftLatLngs} pathOptions={{ color: "#fbbf24", weight: 2 }} />
                )}
                {draftLatLngs.map(([lat, lon], index) => (
                  <Marker key={`${lat}-${lon}-${index}`} position={[lat, lon]} icon={vertexIcon} interactive={false} />
                ))}

                {(cameras ?? []).map((cam) => (
                  <Marker
                    key={cam.camera_id}
                    position={[cam.latitude, cam.longitude]}
                    icon={cameraIcon(cam.camera_id === editingCameraId ? "#fbbf24" : NO_DATA_COLOR)}
                    draggable={!drawing}
                    interactive={!drawing}
                    eventHandlers={{
                      click: () => startEditCamera(cam),
                      dragend: (event) => void handleCameraDragEnd(cam, event as unknown as L.DragEndEvent),
                    }}
                  >
                    <Tooltip>{cam.name}</Tooltip>
                  </Marker>
                ))}
                {pendingCameraPoint && (
                  <Marker position={[pendingCameraPoint.lat, pendingCameraPoint.lon]} icon={vertexIcon} interactive={false} />
                )}
              </>
            ) : (
              <>
                <GeoJSON
                  key={selectedZoneId ?? "none"}
                  data={polygonFeatures}
                  style={styleForFeature}
                  onEachFeature={onEachFeature}
                />
                {cameraFeatures.map((feature) => {
                  if (feature.geometry.type !== "Point") return null;
                  const [lon, lat] = feature.geometry.coordinates;
                  const zoneId = feature.properties?.zone_id as string | undefined;
                  const status = zoneId ? zoneStatus(zoneId) : undefined;
                  const color = status ? STATUS_COLOR[status] : NO_DATA_COLOR;
                  return (
                    <Marker key={feature.properties?.id} position={[lat, lon]} icon={cameraIcon(color)}>
                      <Popup>
                        <strong>{feature.properties?.name}</strong>
                        <br />
                        зона: {zoneId}
                      </Popup>
                    </Marker>
                  );
                })}
              </>
            )}
          </MapContainer>
        </div>

        {editMode && (
          <aside className="sk-panel sk-map-editor">
            {editLoadError && <p className="sk-analysis-page__error">{editLoadError}</p>}

            <div className="sk-map-editor__section">
              <div className="sk-map-editor__section-head">
                <h2>Зоны</h2>
                <button type="button" className="sk-button" disabled={drawing} onClick={startNewZone}>
                  + Новая зона
                </button>
              </div>

              {tool === "draw-zone" && (
                <div className="sk-map-editor__draw-toolbar">
                  <p className="sk-table__muted">
                    {drawingZoneId ? "Перерисуйте контур зоны" : "Отметьте контур зоны"} кликами по карте
                    {draftPoints.length > 0 ? ` (${draftPoints.length} точ.)` : ""}.
                  </p>
                  <div className="sk-map-editor__draw-actions">
                    <button
                      type="button"
                      className="sk-button sk-button--secondary"
                      disabled={draftPoints.length === 0}
                      onClick={undoLastDraftPoint}
                    >
                      Отменить точку
                    </button>
                    <button type="button" className="sk-button" disabled={draftPoints.length < 3} onClick={finishZoneDraw}>
                      Готово
                    </button>
                    <button type="button" className="sk-button sk-button--secondary" onClick={resetDrawState}>
                      Отмена
                    </button>
                  </div>
                </div>
              )}

              {zoneFormOpen && (
                <div className="sk-map-editor__form">
                  <label>
                    Название
                    <input
                      type="text"
                      value={zoneForm.name}
                      onChange={(e) => setZoneForm((f) => ({ ...f, name: e.target.value }))}
                      autoFocus
                    />
                  </label>
                  <label>
                    Тип
                    <select
                      value={zoneForm.kind}
                      onChange={(e) => setZoneForm((f) => ({ ...f, kind: e.target.value as ZoneKind }))}
                    >
                      {zoneKinds.map((k) => (
                        <option key={k.key} value={k.key}>
                          {k.label_ru}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="sk-map-editor__form-actions">
                    <button
                      type="button"
                      className="sk-button"
                      disabled={busy || !zoneForm.name.trim()}
                      onClick={() => void submitZoneForm()}
                    >
                      {drawingZoneId ? "Сохранить контур" : "Создать зону"}
                    </button>
                    <button type="button" className="sk-button sk-button--secondary" onClick={resetDrawState}>
                      Отмена
                    </button>
                  </div>
                </div>
              )}

              <ul className="sk-map-editor__list">
                {(zones ?? []).map((zone) => (
                  <li key={zone.zone_id} className="sk-map-editor__item">
                    {editingZoneId === zone.zone_id ? (
                      <div className="sk-map-editor__form">
                        <label>
                          Название
                          <input
                            type="text"
                            value={zoneMetaForm.name}
                            onChange={(e) => setZoneMetaForm((f) => ({ ...f, name: e.target.value }))}
                          />
                        </label>
                        <label>
                          Тип
                          <select
                            value={zoneMetaForm.kind}
                            onChange={(e) => setZoneMetaForm((f) => ({ ...f, kind: e.target.value as ZoneKind }))}
                          >
                            {zoneKinds.map((k) => (
                              <option key={k.key} value={k.key}>
                                {k.label_ru}
                              </option>
                            ))}
                          </select>
                        </label>
                        <div className="sk-map-editor__form-actions">
                          <button
                            type="button"
                            className="sk-button"
                            disabled={busy || !zoneMetaForm.name.trim()}
                            onClick={() => void submitZoneMeta(zone)}
                          >
                            Сохранить
                          </button>
                          <button
                            type="button"
                            className="sk-button sk-button--secondary"
                            onClick={() => setEditingZoneId(null)}
                          >
                            Отмена
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="sk-map-editor__item-head">
                          <span className="sk-map-editor__swatch" style={{ background: ZONE_KIND_COLOR[zone.kind] }} />
                          <strong>{zone.name}</strong>
                          <span className="sk-table__muted">{zone.kind_label_ru}</span>
                        </div>
                        {pendingDeleteZoneId === zone.zone_id ? (
                          <div className="sk-map-editor__confirm">
                            <span>Удалить «{zone.name}»?</span>
                            <button
                              type="button"
                              className="sk-button sk-settings-danger__confirm-btn"
                              disabled={busy}
                              onClick={() => void confirmDeleteZone(zone.zone_id)}
                            >
                              Да
                            </button>
                            <button
                              type="button"
                              className="sk-button sk-button--secondary"
                              onClick={() => setPendingDeleteZoneId(null)}
                            >
                              Нет
                            </button>
                          </div>
                        ) : (
                          <div className="sk-map-editor__item-actions">
                            <button
                              type="button"
                              className="sk-button sk-button--secondary"
                              disabled={drawing}
                              onClick={() => startEditZoneMeta(zone)}
                            >
                              Название/тип
                            </button>
                            <button
                              type="button"
                              className="sk-button sk-button--secondary"
                              disabled={drawing}
                              onClick={() => startRedrawZone(zone)}
                            >
                              Контур
                            </button>
                            <button
                              type="button"
                              className="sk-button sk-button--secondary"
                              disabled={drawing}
                              onClick={() => setPendingDeleteZoneId(zone.zone_id)}
                            >
                              Удалить
                            </button>
                          </div>
                        )}
                        {(zone.stage_count > 0 || zone.camera_count > 0) && (
                          <p className="sk-map-editor__hint">
                            {[
                              zone.stage_count > 0 ? `этапов: ${zone.stage_count}` : null,
                              zone.camera_count > 0 ? `камер: ${zone.camera_count}` : null,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </p>
                        )}
                      </>
                    )}
                  </li>
                ))}
                {zones !== null && zones.length === 0 && <p className="sk-empty-state">Зон ещё нет.</p>}
              </ul>
            </div>

            <div className="sk-map-editor__section">
              <div className="sk-map-editor__section-head">
                <h2>Камеры</h2>
                <button
                  type="button"
                  className="sk-button"
                  disabled={drawing || (zones ?? []).length === 0}
                  onClick={startPlaceCamera}
                >
                  + Новая камера
                </button>
              </div>
              {(zones ?? []).length === 0 && <p className="sk-table__muted">Сначала создайте хотя бы одну зону.</p>}

              {tool === "place-camera" && !pendingCameraPoint && (
                <p className="sk-table__muted">Кликните на карте, чтобы указать положение камеры.</p>
              )}

              {pendingCameraPoint && (
                <div className="sk-map-editor__form">
                  <label>
                    Название
                    <input
                      type="text"
                      value={cameraForm.name}
                      onChange={(e) => setCameraForm((f) => ({ ...f, name: e.target.value }))}
                      autoFocus
                    />
                  </label>
                  <label>
                    Ссылка на трансляцию (необязательно)
                    <input
                      type="text"
                      value={cameraForm.stream_url}
                      onChange={(e) => setCameraForm((f) => ({ ...f, stream_url: e.target.value }))}
                    />
                  </label>
                  <label>
                    Зона
                    <select
                      value={cameraForm.zone_id}
                      onChange={(e) => setCameraForm((f) => ({ ...f, zone_id: e.target.value }))}
                    >
                      {(zones ?? []).map((z) => (
                        <option key={z.zone_id} value={z.zone_id}>
                          {z.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="sk-map-editor__form-actions">
                    <button
                      type="button"
                      className="sk-button"
                      disabled={busy || !cameraForm.name.trim() || !cameraForm.zone_id}
                      onClick={() => void submitCameraForm()}
                    >
                      Создать камеру
                    </button>
                    <button type="button" className="sk-button sk-button--secondary" onClick={resetDrawState}>
                      Отмена
                    </button>
                  </div>
                </div>
              )}

              <ul className="sk-map-editor__list">
                {(cameras ?? []).map((cam) => (
                  <li key={cam.camera_id} className="sk-map-editor__item">
                    {editingCameraId === cam.camera_id ? (
                      <div className="sk-map-editor__form">
                        <label>
                          Название
                          <input
                            type="text"
                            value={cameraEditForm.name}
                            onChange={(e) => setCameraEditForm((f) => ({ ...f, name: e.target.value }))}
                          />
                        </label>
                        <label>
                          Ссылка на трансляцию
                          <input
                            type="text"
                            value={cameraEditForm.stream_url}
                            onChange={(e) => setCameraEditForm((f) => ({ ...f, stream_url: e.target.value }))}
                          />
                        </label>
                        <label>
                          Зона
                          <select
                            value={cameraEditForm.zone_id}
                            onChange={(e) => setCameraEditForm((f) => ({ ...f, zone_id: e.target.value }))}
                          >
                            {(zones ?? []).map((z) => (
                              <option key={z.zone_id} value={z.zone_id}>
                                {z.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        <div className="sk-map-editor__form-actions">
                          <button
                            type="button"
                            className="sk-button"
                            disabled={busy || !cameraEditForm.name.trim()}
                            onClick={() => void submitCameraEdit(cam)}
                          >
                            Сохранить
                          </button>
                          <button
                            type="button"
                            className="sk-button sk-button--secondary"
                            onClick={() => setEditingCameraId(null)}
                          >
                            Отмена
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="sk-map-editor__item-head">
                          <strong>{cam.name}</strong>
                          <span className="sk-table__muted">{cam.zone_name}</span>
                        </div>
                        {pendingDeleteCameraId === cam.camera_id ? (
                          <div className="sk-map-editor__confirm">
                            <span>Удалить «{cam.name}»?</span>
                            <button
                              type="button"
                              className="sk-button sk-settings-danger__confirm-btn"
                              disabled={busy}
                              onClick={() => void confirmDeleteCamera(cam.camera_id)}
                            >
                              Да
                            </button>
                            <button
                              type="button"
                              className="sk-button sk-button--secondary"
                              onClick={() => setPendingDeleteCameraId(null)}
                            >
                              Нет
                            </button>
                          </div>
                        ) : (
                          <div className="sk-map-editor__item-actions">
                            <button
                              type="button"
                              className="sk-button sk-button--secondary"
                              disabled={drawing}
                              onClick={() => startEditCamera(cam)}
                            >
                              Изменить
                            </button>
                            <button
                              type="button"
                              className="sk-button sk-button--secondary"
                              disabled={drawing}
                              onClick={() => setPendingDeleteCameraId(cam.camera_id)}
                            >
                              Удалить
                            </button>
                          </div>
                        )}
                        <p className="sk-map-editor__hint">Перетащите маркер на карте, чтобы изменить положение.</p>
                      </>
                    )}
                  </li>
                ))}
                {cameras !== null && cameras.length === 0 && <p className="sk-empty-state">Камер ещё нет.</p>}
              </ul>
            </div>

            {actionError && <p className="sk-analysis-page__error">{actionError}</p>}
          </aside>
        )}
      </div>

      {!editMode && (
        <div className="sk-panel" style={{ marginTop: "var(--sk-space-5)" }}>
          <h2>Легенда</h2>
          <ul className="sk-map-legend">
            <li>
              <span style={{ background: STATUS_COLOR.no_deviation }} /> Отклонений не выявлено
            </li>
            <li>
              <span style={{ background: STATUS_COLOR.possible_deviation }} /> Возможное отклонение
            </li>
            <li>
              <span style={{ background: STATUS_COLOR.insufficient_data }} /> Недостаточно данных
            </li>
            <li>
              <span style={{ background: NO_DATA_COLOR }} /> Ещё нет снимков
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}
