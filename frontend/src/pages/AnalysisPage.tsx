import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  createCorrection,
  createObservation,
  fetchCameras,
  fetchSite,
  fetchVocabulary,
  type CameraSummary,
  type Detection,
  type DetectionActivity,
  type ObservationResponse,
  type SiteResponse,
  type VocabularyClassSummary,
} from "../api";
import { useProject } from "../ProjectContext";
import { StatusBadge } from "../components/StatusBadge";
import "./AnalysisPage.css";

const LOW_CONFIDENCE_THRESHOLD = 0.5;
const NOT_EQUIPMENT_OPTION = "__not_equipment__";

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "высокая",
  medium: "средняя",
  low: "низкая",
};

/** «Неопределённо» — равноправный ответ: без зон и истории кадров судить о работе нельзя. */
const ACTIVITY_LABELS: Record<DetectionActivity, string> = {
  working: "работает",
  idle: "простаивает",
  unknown: "неопределённо",
};

type CorrectionStatus = "idle" | "saving" | "saved" | "error";

const CLASS_COLOR_VARS: Record<string, string> = {
  excavator: "var(--sk-class-excavator)",
  dump_truck: "var(--sk-class-dump-truck)",
  mobile_crane: "var(--sk-class-mobile-crane)",
  crane_manipulator: "var(--sk-class-crane-manipulator)",
  concrete_mixer: "var(--sk-class-concrete-mixer)",
  bulldozer: "var(--sk-class-bulldozer)",
  road_roller: "var(--sk-class-road-roller)",
  truck: "var(--sk-class-truck)",
};

function classColor(classKey: string): string {
  return CLASS_COLOR_VARS[classKey] ?? "var(--sk-class-unknown)";
}

interface DetectedGroup {
  classKey: string;
  label: string;
  count: number;
  maxConfidence: number;
}

export function AnalysisPage() {
  const { projectId } = useProject();
  const [site, setSite] = useState<SiteResponse | null>(null);
  const [zoneId, setZoneId] = useState<string>("");
  const [cameras, setCameras] = useState<CameraSummary[]>([]);
  const [cameraId, setCameraId] = useState<string>("");
  const [observedDate, setObservedDate] = useState<string>("");
  const [dateConfirmed, setDateConfirmed] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [result, setResult] = useState<ObservationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const [vocabulary, setVocabulary] = useState<VocabularyClassSummary[]>([]);
  const [correctionChoice, setCorrectionChoice] = useState<Record<number, string>>({});
  const [correctionState, setCorrectionState] = useState<Record<number, CorrectionStatus>>({});

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
    fetchVocabulary()
      .then((data) => {
        if (!cancelled) setVocabulary(data.classes);
      })
      .catch(() => {
        if (!cancelled) setVocabulary([]);
      });
    // Камера нужна для зон кадра и сравнения с предыдущими снимками; если список
    // недоступен, анализ всё равно должен работать — просто без привязки к камере.
    fetchCameras(projectId)
      .then((data) => {
        if (!cancelled) setCameras(data.cameras);
      })
      .catch(() => {
        if (!cancelled) setCameras([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Камера из другой зоны смотрит на другой участок: её зоны кадра к этому
  // снимку не относятся, поэтому при смене зоны выбор сбрасывается.
  useEffect(() => {
    setCameraId((current) => {
      const camera = cameras.find((item) => item.camera_id === current);
      return camera && camera.zone_id === zoneId ? current : "";
    });
  }, [zoneId, cameras]);

  const onFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
    setResult(null);
    setImageSize(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(selected ? URL.createObjectURL(selected) : null);
  };

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file || !zoneId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await createObservation({
        projectId,
        zoneId,
        observedDate: observedDate || undefined,
        dateConfirmed,
        cameraId: cameraId || undefined,
        image: file,
      });
      setResult(response);
      setCorrectionChoice({});
      setCorrectionState({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось выполнить анализ");
    } finally {
      setLoading(false);
    }
  };

  const submitCorrection = async (index: number, detection: Detection) => {
    if (!result) return;
    const chosen = correctionChoice[index] ?? detection.class_key;
    setCorrectionState((s) => ({ ...s, [index]: "saving" }));
    try {
      await createCorrection({
        projectId,
        observationId: result.observation_id,
        bbox: detection.bbox,
        originalClassKey: detection.class_key,
        originalConfidence: detection.confidence,
        correctedClassKey: chosen === NOT_EQUIPMENT_OPTION ? null : chosen,
      });
      setCorrectionState((s) => ({ ...s, [index]: "saved" }));
    } catch {
      setCorrectionState((s) => ({ ...s, [index]: "error" }));
    }
  };

  const zoneFeatures = site?.geojson.features.filter((f) => f.properties?.kind === "zone") ?? [];
  const zoneCameras = cameras.filter((camera) => camera.zone_id === zoneId);

  const detectedGroups: DetectedGroup[] = [];
  if (result) {
    const byClass = new Map<string, DetectedGroup>();
    for (const d of result.detections) {
      if (!d.in_taxonomy || d.ambiguous) continue;
      const existing = byClass.get(d.class_key);
      if (existing) {
        existing.count += 1;
        existing.maxConfidence = Math.max(existing.maxConfidence, d.confidence);
      } else {
        byClass.set(d.class_key, { classKey: d.class_key, label: d.label_ru, count: 1, maxConfidence: d.confidence });
      }
    }
    detectedGroups.push(...Array.from(byClass.values()).sort((a, b) => b.maxConfidence - a.maxConfidence));
  }

  const primaryStage = result?.stages[0] ?? null;
  const deviatingStage = result?.stages.find((s) => s.status !== "no_deviation") ?? primaryStage;

  // Блок ИИ может отсутствовать целиком (старый ответ или отключённая модель) —
  // интерфейс в этом случае просто не показывает соответствующие карточки.
  const vision = result?.ai?.vision ?? null;
  const mismatch = result?.ai?.stage_mismatch ?? null;
  const conclusion = result?.ai?.conclusion ?? null;
  const zoneFindings = result?.ai?.zone_deviations ?? [];

  // Строки про работу и простой показываются только для уверенных детекций:
  // рассуждать об активности объекта, класс которого под вопросом, смысла нет.
  const activityRows = (result?.detections ?? []).filter(
    (detection) => detection.in_taxonomy && !detection.ambiguous && detection.activity,
  );
  const activityKnown = activityRows.some((detection) => detection.activity !== "unknown");

  const reviewDetections = (result?.detections ?? [])
    .map((detection, index) => ({ detection, index }))
    .filter(
      ({ detection }) =>
        detection.ambiguous || (detection.in_taxonomy && detection.confidence < LOW_CONFIDENCE_THRESHOLD),
    );

  return (
    <div className="sk-analysis-page">
      <h1>Камера — AI-анализ</h1>

      <div className="sk-analysis-page__grid">
        <form className="sk-panel sk-analysis-page__form" onSubmit={onSubmit}>
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
            <label htmlFor="camera">Камера</label>
            <select id="camera" value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
              <option value="">Не указана — без зон кадра</option>
              {zoneCameras.map((camera) => (
                <option key={camera.camera_id} value={camera.camera_id}>
                  {camera.name}
                </option>
              ))}
            </select>
            <span className="sk-field__hint">
              {cameraId ? (
                <>
                  С указанной камерой система определяет работу и простой по зонам кадра.{" "}
                  <Link to={`/projects/${projectId}/cameras/${cameraId}/zones`}>Разметить зоны</Link>
                </>
              ) : zoneCameras.length === 0 ? (
                "В этой зоне нет камер: работа и простой определены не будут."
              ) : (
                "Без камеры зоны кадра и сравнение с предыдущими снимками не применяются."
              )}
            </span>
          </div>

          <div className="sk-field">
            <label htmlFor="date">Дата съёмки</label>
            <input
              id="date"
              type="date"
              value={observedDate}
              onChange={(e) => setObservedDate(e.target.value)}
            />
          </div>

          <label className="sk-checkbox">
            <input
              type="checkbox"
              checked={dateConfirmed}
              onChange={(e) => setDateConfirmed(e.target.checked)}
              disabled={!observedDate}
            />
            Дата подтверждена (вручную или по штампу на снимке)
          </label>

          <div className="sk-field">
            <label htmlFor="image">Снимок</label>
            <input id="image" type="file" accept="image/*" onChange={onFileChange} />
          </div>

          {previewUrl && (
            <div className="sk-analysis-page__preview">
              <img
                src={previewUrl}
                alt="Предпросмотр снимка"
                onLoad={(event) => {
                  const target = event.currentTarget;
                  setImageSize({ width: target.naturalWidth, height: target.naturalHeight });
                }}
              />
              {imageSize &&
                result?.detections.map((detection, index) => {
                const naturalWidth = imageSize.width || 1;
                const naturalHeight = imageSize.height || 1;
                const [x1, y1, x2, y2] = detection.bbox;
                const color = detection.ambiguous
                  ? "var(--sk-status-warning)"
                  : !detection.in_taxonomy
                    ? "var(--sk-class-unknown)"
                    : classColor(detection.class_key);
                return (
                  <div
                    key={index}
                    className={`sk-bbox${detection.ambiguous ? " sk-bbox--ambiguous" : ""}${
                      !detection.in_taxonomy ? " sk-bbox--distractor" : ""
                    }`}
                    style={{
                      left: `${(x1 / naturalWidth) * 100}%`,
                      top: `${(y1 / naturalHeight) * 100}%`,
                      width: `${((x2 - x1) / naturalWidth) * 100}%`,
                      height: `${((y2 - y1) / naturalHeight) * 100}%`,
                      borderColor: color,
                    }}
                    title={`${detection.label_ru} ${(detection.confidence * 100).toFixed(0)}%${
                      detection.activity_reason ? ` · ${detection.activity_reason}` : ""
                    }`}
                  >
                    <span className="sk-bbox__label" style={{ backgroundColor: color }}>
                      {detection.label_ru} {(detection.confidence * 100).toFixed(0)}%
                      {detection.ambiguous ? " · неоднозначно" : ""}
                      {/* Простой подписывается прямо на рамке: это главный вопрос заказчика к снимку. */}
                      {detection.activity === "idle" ? " · простой" : ""}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          <button type="submit" className="sk-button" disabled={!file || loading}>
            {loading ? "Анализируем…" : "Проверить снимок"}
          </button>
          {error && <p className="sk-analysis-page__error">{error}</p>}
        </form>

        <div className="sk-analysis-page__result">
          {!result && (
            <div className="sk-panel">
              <p className="sk-empty-state">Загрузите снимок, чтобы увидеть результат.</p>
            </div>
          )}
          {result && (
            <>
              <div className="sk-panel">
                <h2>Результат анализа</h2>
                <p className="sk-table__muted">Обнаружено объектов: {detectedGroups.reduce((s, g) => s + g.count, 0)}</p>
                <table className="sk-table">
                  <thead>
                    <tr>
                      <th>Объект</th>
                      <th>Кол-во</th>
                      <th>Уверенность</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detectedGroups.map((g) => (
                      <tr key={g.classKey}>
                        <td>
                          <span
                            className="sk-class-dot"
                            style={{ background: classColor(g.classKey) }}
                            aria-hidden="true"
                          />
                          {g.label}
                        </td>
                        <td>{g.count}</td>
                        <td>{(g.maxConfidence * 100).toFixed(0)}%</td>
                      </tr>
                    ))}
                    {detectedGroups.length === 0 && (
                      <tr>
                        <td colSpan={3} className="sk-table__muted">
                          Требуемая техника не распознана уверенно
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="sk-panel sk-analysis-page__overall">
                <StatusBadge status={result.overall_status} label={result.overall_status_label_ru} />
                <p>{result.overall_explanation_ru}</p>
                <p className="sk-table__muted">
                  Зона {result.zone_id}
                  {primaryStage && <> · этап «{primaryStage.work_name}»</>}
                  {result.saved_to_db ? " · сохранено в истории" : " · БД недоступна, сохранить не удалось"}
                </p>
              </div>

              {activityKnown && (
                <div className="sk-panel">
                  <h2>Работа или простой</h2>
                  <table className="sk-table">
                    <thead>
                      <tr>
                        <th>Техника</th>
                        <th>Зона кадра</th>
                        <th>Состояние</th>
                        <th>Основание</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activityRows.map((detection, index) => (
                        <tr key={`${detection.class_key}-${index}`}>
                          <td>
                            <span
                              className="sk-class-dot"
                              style={{ background: classColor(detection.class_key) }}
                              aria-hidden="true"
                            />
                            {detection.label_ru}
                          </td>
                          <td>{detection.frame_zone_name ?? "вне размеченных зон"}</td>
                          <td>{ACTIVITY_LABELS[detection.activity ?? "unknown"]}</td>
                          <td className="sk-table__muted">{detection.activity_reason ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {zoneFindings.length > 0 && (
                <div className="sk-panel">
                  <h2>Отклонения по зонам</h2>
                  {zoneFindings.map((finding) => (
                    <div
                      key={finding.kind}
                      className={`sk-zone-finding sk-zone-finding--${finding.severity}`}
                    >
                      <h3>{finding.title}</h3>
                      <p>{finding.message}</p>
                    </div>
                  ))}
                </div>
              )}

              {vision?.available && (
                <div className="sk-panel sk-vision-card">
                  <div className="sk-vision-card__header">
                    <h2>Стадия по снимку</h2>
                    <span className="sk-vision-card__confidence">
                      уверенность: {CONFIDENCE_LABELS[vision.confidence]}
                    </span>
                  </div>
                  <p className="sk-vision-card__stage">{vision.stage_label}</p>

                  {vision.readiness_percent !== null && (
                    <div className="sk-readiness">
                      <div className="sk-readiness__head">
                        <span>Готовность объекта</span>
                        <strong>{vision.readiness_percent}%</strong>
                      </div>
                      <div className="sk-readiness__track">
                        <div
                          className="sk-readiness__fill"
                          style={{ width: `${vision.readiness_percent}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {vision.visual_evidence.length > 0 && (
                    <>
                      <p className="sk-table__muted">На чём основан вывод:</p>
                      <ul className="sk-vision-card__evidence">
                        {vision.visual_evidence.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </>
                  )}

                  <p className="sk-table__muted">
                    {vision.date_stamp
                      ? `Штамп даты на снимке: ${vision.date_stamp}`
                      : "Штамп даты на снимке не обнаружен"}
                    {vision.cached && " · результат из кэша"}
                  </p>
                </div>
              )}

              {mismatch && (
                <div className="sk-panel sk-mismatch-card">
                  <h2>Расхождение с графиком</h2>
                  <p>{mismatch.message}</p>
                  <p className="sk-table__muted">
                    На снимке: {mismatch.observed_stage} · По графику: {mismatch.scheduled_stages}
                  </p>
                </div>
              )}

              {conclusion && (
                <div className="sk-panel sk-conclusion-card">
                  <h2>Заключение для руководителя</h2>
                  {conclusion.available ? (
                    <>
                      <p className="sk-conclusion-card__text">{conclusion.text}</p>
                      <p className="sk-table__muted">
                        Сформировано моделью {conclusion.model || "—"}
                        {conclusion.cached && " · из кэша"} по данным проверки выше
                      </p>
                    </>
                  ) : (
                    <p className="sk-table__muted">
                      Заключение не сформировано: языковая модель недоступна
                      {conclusion.error ? ` (${conclusion.error})` : ""}. Результат проверки выше остаётся действительным.
                    </p>
                  )}
                </div>
              )}

              {result.stages.map((stage) => (
                <div key={stage.stage_id} className="sk-panel sk-stage-card">
                  <div className="sk-stage-card__header">
                    <h3>{stage.work_name}</h3>
                    <StatusBadge status={stage.status} label={stage.status_label_ru} />
                  </div>
                  {stage.is_critical && (
                    <p className="sk-stage-card__critical">
                      Этап на критическом пути: запаса времени нет, отставание по нему напрямую
                      сдвигает дату сдачи объекта.
                    </p>
                  )}
                  <p>{stage.explanation_ru}</p>

                  {stage.quantity_checks.length > 0 && (
                    <table className="sk-table" style={{ marginTop: "var(--sk-space-2)" }}>
                      <thead>
                        <tr>
                          <th>Техника</th>
                          <th>План</th>
                          <th>Факт</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {stage.quantity_checks.map((c) => (
                          <tr key={c.class_key}>
                            <td>
                              <span className="sk-class-dot" style={{ background: classColor(c.class_key) }} aria-hidden="true" />
                              {c.label_ru}
                            </td>
                            <td>{c.required_qty}</td>
                            <td>{c.actual_qty}</td>
                            <td>{c.satisfied ? "✅" : "⚠"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}

                  <p className="sk-stage-card__meta">
                    Требуется: {stage.required.join(", ") || "—"} · Допустимо:{" "}
                    {stage.allowed.join(", ") || "—"}
                  </p>
                </div>
              ))}

              {reviewDetections.length > 0 && (
                <div className="sk-panel">
                  <h2>Требует уточнения</h2>
                  <p className="sk-table__muted">
                    Неоднозначные или низкоуверенные детекции — укажите правильный класс, чтобы
                    обучить классификатор-корректор (см. «Центр обучения AI»).
                  </p>
                  {!result.saved_to_db && (
                    <p className="sk-table__muted">Коррекции доступны только для сохранённых в БД наблюдений.</p>
                  )}
                  <table className="sk-table">
                    <thead>
                      <tr>
                        <th>Обнаружено</th>
                        <th>Уверенность</th>
                        <th>Правильный класс</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {reviewDetections.map(({ detection, index }) => {
                        const state = correctionState[index] ?? "idle";
                        const disabled = !result.saved_to_db || state === "saving" || state === "saved";
                        return (
                          <tr key={index}>
                            <td>
                              {detection.label_ru}
                              {detection.ambiguous ? " · неоднозначно" : ""}
                            </td>
                            <td>{(detection.confidence * 100).toFixed(0)}%</td>
                            <td>
                              <select
                                value={correctionChoice[index] ?? detection.class_key}
                                onChange={(e) =>
                                  setCorrectionChoice((c) => ({ ...c, [index]: e.target.value }))
                                }
                                disabled={disabled}
                              >
                                {vocabulary.map((cls) => (
                                  <option key={cls.key} value={cls.key}>
                                    {cls.label_ru}
                                  </option>
                                ))}
                                <option value={NOT_EQUIPMENT_OPTION}>Другое / не техника</option>
                              </select>
                            </td>
                            <td>
                              {state === "saved" ? (
                                <span>Сохранено ✅</span>
                              ) : (
                                <button
                                  type="button"
                                  className="sk-button sk-button--secondary"
                                  disabled={disabled}
                                  onClick={() => submitCorrection(index, detection)}
                                >
                                  {state === "saving" ? "Сохраняем…" : "Сохранить"}
                                </button>
                              )}
                              {state === "error" && (
                                <p className="sk-analysis-page__error">Не удалось сохранить</p>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {deviatingStage && (
                <details className="sk-panel sk-explain-panel">
                  <summary>Почему возникло отклонение?</summary>
                  <ol className="sk-explain-chain">
                    <li>
                      Этап: <strong>{deviatingStage.work_name}</strong>
                    </li>
                    <li>Требуется: {deviatingStage.required.join(", ") || "—"}</li>
                    <li>
                      Обнаружено:{" "}
                      {detectedGroups.length > 0
                        ? detectedGroups.map((g) => `${g.label} ×${g.count}`).join(", ")
                        : "требуемая техника не обнаружена уверенно"}
                    </li>
                    <li>Вывод: {deviatingStage.explanation_ru}</li>
                  </ol>
                </details>
              )}

              {previewUrl && (
                <div className="sk-panel">
                  <h2>Доказательство</h2>
                  <img src={previewUrl} alt="Снимок-доказательство" className="sk-evidence-thumb" />
                  <a href={previewUrl} target="_blank" rel="noreferrer" className="sk-button sk-button--secondary" style={{ marginTop: "var(--sk-space-3)", display: "inline-block" }}>
                    Открыть в полном размере
                  </a>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
