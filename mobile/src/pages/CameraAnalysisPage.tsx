import { useEffect, useState } from "react";
import { Camera, CameraResultType, CameraSource } from "@capacitor/camera";
import { createObservation, fetchSite, type ObservationResponse, type SiteResponse } from "../api";
import { useProject } from "../ProjectContext";
import "./CameraAnalysisPage.css";

export function CameraAnalysisPage() {
  const { projectId } = useProject();
  const [site, setSite] = useState<SiteResponse | null>(null);
  const [zoneId, setZoneId] = useState("");
  const [dateConfirmed, setDateConfirmed] = useState(false);
  const [observedDate, setObservedDate] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [photoBlob, setPhotoBlob] = useState<Blob | null>(null);
  const [result, setResult] = useState<ObservationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSite(null);
    setZoneId("");
    setResult(null);
    fetchSite(projectId).then((data) => {
      if (cancelled) return;
      setSite(data);
      const firstZone = data.geojson.features.find((f) => f.properties?.kind === "zone");
      if (firstZone) setZoneId(firstZone.properties?.id);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const zoneFeatures = site?.geojson.features.filter((f) => f.properties?.kind === "zone") ?? [];

  const takePhoto = async () => {
    setError(null);
    try {
      const photo = await Camera.getPhoto({
        resultType: CameraResultType.Uri,
        source: CameraSource.Prompt,
        quality: 85,
        promptLabelHeader: "Снимок для анализа",
        promptLabelPhoto: "Выбрать из галереи",
        promptLabelPicture: "Сделать снимок",
      });
      if (!photo.webPath) return;
      const blob = await fetch(photo.webPath).then((r) => r.blob());
      setPhotoBlob(blob);
      setPreviewUrl(photo.webPath);
      setResult(null);
    } catch {
      // Пользователь отменил выбор снимка — не ошибка, ничего не делаем.
    }
  };

  const onSubmit = async () => {
    if (!photoBlob || !zoneId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await createObservation({
        projectId,
        zoneId,
        observedDate: observedDate || undefined,
        dateConfirmed,
        image: photoBlob,
        fileName: "photo.jpg",
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось выполнить анализ");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1>Камера — AI-анализ</h1>

      <div className="sk-panel">
        <div className="sk-field">
          <label htmlFor="zone">Зона</label>
          <select id="zone" value={zoneId} onChange={(e) => setZoneId(e.target.value)}>
            {zoneFeatures.map((feature) => (
              <option key={feature.properties?.id} value={feature.properties?.id}>
                {feature.properties?.name}
              </option>
            ))}
          </select>
        </div>

        <div className="sk-field">
          <label htmlFor="date">Дата съёмки</label>
          <input id="date" type="date" value={observedDate} onChange={(e) => setObservedDate(e.target.value)} />
        </div>

        <label className="sk-checkbox">
          <input
            type="checkbox"
            checked={dateConfirmed}
            onChange={(e) => setDateConfirmed(e.target.checked)}
            disabled={!observedDate}
          />
          Дата подтверждена
        </label>

        {previewUrl && <img src={previewUrl} alt="Предпросмотр снимка" className="sk-camera-preview" />}

        <button type="button" className="sk-button sk-button--secondary sk-button--block" onClick={takePhoto}>
          {previewUrl ? "Выбрать другой снимок" : "Сделать снимок"}
        </button>

        <button
          type="button"
          className="sk-button sk-button--block"
          style={{ marginTop: "var(--sk-space-3)" }}
          disabled={!photoBlob || !zoneId || loading}
          onClick={onSubmit}
        >
          {loading ? "Анализируем…" : "Проверить снимок"}
        </button>

        {error && <p className="sk-camera-analysis__error">{error}</p>}
      </div>

      {result && (
        <div className="sk-panel" style={{ marginTop: "var(--sk-space-4)" }}>
          <h2>{result.overall_status_label_ru}</h2>
          <p className="sk-table__muted">{result.overall_explanation_ru}</p>
          {result.stages.map((stage) => (
            <div key={stage.stage_id} className="sk-camera-analysis__stage">
              <strong>{stage.work_name}</strong>
              <p className="sk-table__muted">{stage.explanation_ru}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
