import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  fetchAnalytics,
  fetchCamera,
  fetchDashboard,
  fetchDeviations,
  fetchObservation,
  fetchSite,
  fetchZoneStagesOnDate,
  getObservationImageUrl,
  type AnalyticsResponse,
  type CameraSummary,
  type DashboardResponse,
  type DeviationRecord,
  type ObservationDetail,
  type ObservationSummary,
  type QuantityCheck,
  type SiteResponse,
  type ZoneStageOnDate,
} from "../api";
import { useProject } from "../ProjectContext";
import { MiniSiteMap } from "../components/MiniSiteMap";
import { EquipmentIcon } from "../components/EquipmentIcons";
import { CameraStatIcon, ChartStatIcon, WarningStatIcon } from "../components/DashboardIcons";
import "./DashboardPage.css";

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

const SEVERITY_ICON: Record<string, string> = {
  critical: "⚠",
  warning: "⏱",
  info: "ℹ",
};

const OPEN_STATUSES = new Set(["detected", "assigned"]);

function StatCard({
  icon,
  value,
  label,
  hint,
  accent,
}: {
  icon: ReactNode;
  value: string | number;
  label: string;
  hint?: string;
  accent?: "ok" | "warning" | "danger";
}) {
  return (
    <div className="sk-panel sk-stat-card">
      <span className={`sk-stat-card__icon${accent ? ` sk-stat-card__icon--${accent}` : ""}`} aria-hidden="true">
        {icon}
      </span>
      <div>
        <div className="sk-stat-card__value">{value}</div>
        <div className="sk-stat-card__label">{label}</div>
        {hint && (
          <div className={`sk-stat-card__hint${accent ? ` sk-stat-card__hint--${accent}` : ""}`}>{hint}</div>
        )}
      </div>
    </div>
  );
}

/** Компактный столбчатый график с подписями дат — карточка «Динамика отклонений» в нижнем ряду. */
function MiniBarChart({ data }: { data: { label: string; value: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="sk-mini-bar-chart">
      {data.map((d, index) => (
        <div key={index} className="sk-mini-bar-chart__col">
          <div className="sk-mini-bar-chart__track">
            <div
              className="sk-mini-bar-chart__bar"
              style={{ height: `${(d.value / max) * 100}%` }}
              title={`${d.label}: ${d.value}`}
            />
          </div>
          <span className="sk-mini-bar-chart__label">{d.label}</span>
        </div>
      ))}
    </div>
  );
}

/** Мини-карточки план/факт по технике — карточка «Техника на площадке» в нижнем ряду. */
function EquipmentMiniGrid({
  checks,
  fallbackGroups,
}: {
  checks: QuantityCheck[];
  fallbackGroups: { classKey: string; label: string; count: number }[];
}) {
  if (checks.length > 0) {
    return (
      <div className="sk-eq-grid">
        {checks.map((q) => (
          <div key={q.class_key} className={`sk-eq${q.satisfied ? " sk-eq--ok" : " sk-eq--bad"}`}>
            <EquipmentIcon classKey={q.class_key} className="sk-eq__icon" style={{ color: classColor(q.class_key) }} />
            <div className="sk-eq__count">
              {q.actual_qty}/{q.required_qty}
            </div>
            <div className="sk-eq__label">{q.label_ru}</div>
          </div>
        ))}
      </div>
    );
  }
  if (fallbackGroups.length > 0) {
    return (
      <>
        <p className="sk-table__muted">Показаны только распознанные объекты</p>
        <div className="sk-eq-grid">
          {fallbackGroups.map((g) => (
            <div key={g.classKey} className="sk-eq sk-eq--neutral">
              <EquipmentIcon classKey={g.classKey} className="sk-eq__icon" style={{ color: classColor(g.classKey) }} />
              <div className="sk-eq__count">{g.count}</div>
              <div className="sk-eq__label">{g.label}</div>
            </div>
          ))}
        </div>
      </>
    );
  }
  return <p className="sk-empty-state">Техника не распознана.</p>;
}

export function DashboardPage() {
  const { projectId, project } = useProject();
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [site, setSite] = useState<SiteResponse | null>(null);
  const [deviations, setDeviations] = useState<DeviationRecord[] | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [selectedCameraId, setSelectedCameraId] = useState<string>("");
  const [observation, setObservation] = useState<ObservationDetail | null>(null);
  const [observationError, setObservationError] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  // История снимков камеры для прокрутки назад с Главной: cameraHistory[0] — самый
  // свежий снимок ("онлайн"), historyIndex > 0 — режим просмотра истории.
  const [cameraHistory, setCameraHistory] = useState<ObservationSummary[] | null>(null);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [historyStageInfo, setHistoryStageInfo] = useState<ZoneStageOnDate | null>(null);
  const [frameSize, setFrameSize] = useState<{ width: number; height: number } | null>(null);
  const frameObserverRef = useRef<ResizeObserver | null>(null);

  // Кадр камеры может не совпадать по пропорциям с фото (letterboxing через
  // object-fit: contain) — отслеживаем реальный размер кадра, чтобы точно
  // спроецировать bbox-рамки на фактически отображаемую картинку.
  //
  // ИСПОЛЬЗУЕМ CALLBACK REF, А НЕ useEffect(..., []) + обычный useRef: пока данные дашборда ещё
  // не загрузились, компонент рендерит плейсхолдер «Загрузка сводки…» без реального элемента
  // рамки, поэтому useEffect с пустыми зависимостями (запускающийся ровно один раз за
  // всё время жизни компонента) видел ref.current === null и никогда больше не перезапускался
  // после того, как данные загружались и реальная рамка появилась в DOM — frameSize оставался null
  // навсегда, и bbox-рамки никогда не рисовались. Callback ref вызывается каждый раз, когда
  // элемент реально монтируется/размонтируется, независимо от того, на каком рендере это произошло.
  //
  // Раньше высота всей страницы принудительно подгонялась под высоту экрана (чтобы избежать
  // прокрутки страницы), из-за чего на невысоких экранах (ноутбуки с масштабированием)
  // рамка фото сжималась до крошечного min-height, и фото превращалось в тонкую полоску —
  // выглядело как «обрезание», хотя object-fit:contain ничего технически не обрезал. Теперь
  // у рамки есть достаточный min-height (см. DashboardPage.css), а страница при нехватке места
  // просто скроллится, а не сжимает фото.
  const setFrameRef = useCallback((el: HTMLDivElement | null) => {
    frameObserverRef.current?.disconnect();
    frameObserverRef.current = null;
    if (!el) return;
    const update = () => setFrameSize({ width: el.clientWidth, height: el.clientHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    frameObserverRef.current = observer;
  }, []);

  useEffect(() => {
    let cancelled = false;
    setDashboard(null);
    setSite(null);
    setDeviations(null);
    setAnalytics(null);
    setError(null);
    setSelectedCameraId("");

    Promise.all([fetchDashboard(projectId), fetchSite(projectId)])
      .then(([d, s]) => {
        if (cancelled) return;
        setDashboard(d);
        setSite(s);
        if (d.cameras.length > 0) setSelectedCameraId(d.cameras[0].camera_id);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });

    // Отклонения и аналитика грузятся отдельно и не блокируют экран.
    fetchDeviations(projectId)
      .then((data) => !cancelled && setDeviations(data.items))
      .catch(() => !cancelled && setDeviations([]));
    fetchAnalytics(projectId, 14)
      .then((data) => !cancelled && setAnalytics(data))
      .catch(() => !cancelled && setAnalytics(null));

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const cameras: CameraSummary[] = dashboard?.cameras ?? [];
  const selectedCamera = cameras.find((c) => c.camera_id === selectedCameraId) ?? null;

  // История снимков камеры (для кнопок "Назад"/"Вперёд") грузится отдельно при смене
  // камеры; сбрасываем прокрутку на "онлайн" каждый раз, когда выбор камеры меняется.
  useEffect(() => {
    let cancelled = false;
    setCameraHistory(null);
    setHistoryIndex(0);
    if (!selectedCameraId) return;
    fetchCamera(projectId, selectedCameraId)
      .then((data) => !cancelled && setCameraHistory(data.recent_observations))
      .catch(() => !cancelled && setCameraHistory(null));
    return () => {
      cancelled = true;
    };
  }, [projectId, selectedCameraId]);

  const hasOlderHistory = Boolean(cameraHistory && historyIndex < cameraHistory.length - 1);
  const isHistoryMode = historyIndex > 0;
  const displayedObservationSummary =
    (cameraHistory && cameraHistory[historyIndex]) ?? selectedCamera?.latest_observation ?? null;
  const selectedObservationId = displayedObservationSummary?.observation_id ?? null;

  // Полный разбор (детекции + план/факт по этапу) грузится под выбранный снимок отдельно:
  // сводка `/dashboard`/`/cameras/{id}` отдаёт только статус, без списка объектов.
  useEffect(() => {
    let cancelled = false;
    setObservation(null);
    setObservationError(null);
    setImageSize(null);
    if (!selectedObservationId) return;
    fetchObservation(projectId, selectedObservationId)
      .then((data) => !cancelled && setObservation(data))
      .catch((err: Error) => !cancelled && setObservationError(err.message));
    return () => {
      cancelled = true;
    };
  }, [projectId, selectedObservationId]);

  // В режиме просмотра истории "Текущий этап" должен показывать этап, актуальный на
  // дату просматриваемого снимка, а не сегодняшний — иначе прокрутка назад теряет смысл.
  useEffect(() => {
    let cancelled = false;
    setHistoryStageInfo(null);
    if (!isHistoryMode || !selectedCamera || !displayedObservationSummary) return;
    const onDate = displayedObservationSummary.observed_date ?? displayedObservationSummary.created_at.slice(0, 10);
    fetchZoneStagesOnDate(projectId, selectedCamera.zone_id, onDate)
      .then((data) => !cancelled && setHistoryStageInfo(data.stages[0] ?? null))
      .catch(() => !cancelled && setHistoryStageInfo(null));
    return () => {
      cancelled = true;
    };
  }, [projectId, isHistoryMode, selectedCamera, displayedObservationSummary]);

  // Неоднозначные классы (excavator/mobile_crane/crane_manipulator/road_roller — см.
  // ConfusablePair в БД) всё равно попадают в легенду: иначе эти классы никогда не появились бы в сводке,
  // хотя рамки для них уже рисуются на кадре. Честность сохраняется отдельной
  // пометкой «?» у таких пунктов, а не молчаливым исключением.
  const detectedGroups = useMemo(() => {
    const byClass = new Map<string, { classKey: string; label: string; count: number; ambiguous: boolean }>();
    for (const d of observation?.detections ?? []) {
      if (!d.in_taxonomy) continue;
      const existing = byClass.get(d.class_key);
      if (existing) {
        existing.count += 1;
        existing.ambiguous = existing.ambiguous && d.ambiguous;
      } else {
        byClass.set(d.class_key, { classKey: d.class_key, label: d.label_ru, count: 1, ambiguous: d.ambiguous });
      }
    }
    return Array.from(byClass.values());
  }, [observation]);

  // Фактический размер кадра (может отличаться от пропорций фото из-за letterboxing через
  // object-fit: contain) — вычисляем фактический прямоугольник картинки внутри кадра,
  // чтобы bbox-рамки не «уезжали» в пустые поля по краям.
  const displayRect = useMemo(() => {
    if (!imageSize || !frameSize || !imageSize.width || !imageSize.height || !frameSize.width || !frameSize.height) {
      return null;
    }
    const imageRatio = imageSize.width / imageSize.height;
    const frameRatio = frameSize.width / frameSize.height;
    let width: number;
    let height: number;
    if (frameRatio > imageRatio) {
      height = frameSize.height;
      width = height * imageRatio;
    } else {
      width = frameSize.width;
      height = width / imageRatio;
    }
    return { width, height, offsetX: (frameSize.width - width) / 2, offsetY: (frameSize.height - height) / 2 };
  }, [imageSize, frameSize]);

  const matchedStage = useMemo(() => {
    if (!observation || observation.stages.length === 0) return null;
    const currentStageId = isHistoryMode ? historyStageInfo?.stage_id : dashboard?.current_stage?.stage_id;
    return observation.stages.find((s) => s.stage_id === currentStageId) ?? observation.stages[0];
  }, [observation, isHistoryMode, historyStageInfo?.stage_id, dashboard?.current_stage?.stage_id]);

  // Для архивного этапа прогресс считаем локально как долю прошедшего времени от начала до даты
  // снимка в границах этапа — бэкенд отдаёт процент только для сегодняшнего этапа.
  const historyStageProgressPercent = useMemo(() => {
    if (!isHistoryMode || !historyStageInfo || !displayedObservationSummary) return null;
    const onDate =
      displayedObservationSummary.observed_date ?? displayedObservationSummary.created_at.slice(0, 10);
    const start = new Date(historyStageInfo.start_date).getTime();
    const end = new Date(historyStageInfo.end_date).getTime();
    const current = new Date(onDate).getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
    return Math.round(Math.min(100, Math.max(0, ((current - start) / (end - start)) * 100)));
  }, [isHistoryMode, historyStageInfo, displayedObservationSummary]);

  const quantityChecks = matchedStage?.quantity_checks ?? [];

  const boundaryFeature = site?.geojson.features.find((f) => f.properties?.kind === "site_boundary");
  const mapCenter = useMemo<[number, number] | null>(() => {
    if (boundaryFeature && boundaryFeature.geometry.type === "Polygon") {
      const ring = boundaryFeature.geometry.coordinates[0];
      const lats = ring.map(([, lat]) => lat);
      const lons = ring.map(([lon]) => lon);
      return [lats.reduce((a, b) => a + b, 0) / lats.length, lons.reduce((a, b) => a + b, 0) / lons.length];
    }
    if (project.latitude !== null && project.longitude !== null) return [project.latitude, project.longitude];
    return null;
  }, [boundaryFeature, project.latitude, project.longitude]);

  const zoneStatus = (zoneId: string) =>
    dashboard?.zones.find((z) => z.zone_id === zoneId)?.latest_observation?.overall_status;

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить сводку: {error}</div>;
  }
  if (!dashboard || !site) {
    return <div className="sk-panel">Загрузка сводки…</div>;
  }

  const openDeviations = (deviations ?? []).filter((d) => OPEN_STATUSES.has(d.status));
  const criticalOpenCount = openDeviations.filter((d) => d.severity === "critical").length;
  const topCriticalDeviation = openDeviations.find((d) => d.severity === "critical") ?? null;

  // План/факт для критического уведомления на кадре — берём точные числа из проверки
  // текущего этапа, а не парсим текст отклонения.
  const toastShortfalls = quantityChecks.filter(
    (c) => !c.satisfied && topCriticalDeviation?.equipment.includes(c.class_key),
  );

  // Карточки подбираются не просто по дате, а по одному самому свежему на каждый уровень важности
  // (критическое / предупреждение / инфо) — при чисто хронологической сортировке верхние
  // позиции часто занимают один и тот же повторяющийся тип отклонения.
  const latestBySeverity = (severity: DeviationRecord["severity"]) =>
    [...(deviations ?? [])]
      .filter((d) => d.severity === severity)
      .sort((a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime())[0];

  const curatedDeviations = (["critical", "warning", "info"] as const)
    .map(latestBySeverity)
    .filter((d): d is DeviationRecord => Boolean(d));
  const curatedIds = new Set(curatedDeviations.map((d) => d.id));
  const fallbackDeviations = [...(deviations ?? [])]
    .filter((d) => !curatedIds.has(d.id))
    .sort((a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime());
  const recentDeviations = [...curatedDeviations, ...fallbackDeviations].slice(0, 3);

  const deviationsByDay = (analytics?.deviations_by_month ?? []).map((d) => ({
    // "YYYY-MM" надёжно парсится как дата только с днём — см. аналогичный комментарий в AnalyticsPage.tsx.
    label: new Date(`${d.month}-01`).toLocaleDateString("ru-RU", { month: "short", year: "numeric" }),
    value: d.count,
  }));
  const deviationsByDayTotal = deviationsByDay.reduce((sum, d) => sum + d.value, 0);

  const onlineCameraCount = cameras.filter((c) => c.stream_url).length;

  return (
    <div className="sk-dashboard">
      {site.schedule_is_demo && (
        <p className="sk-demo-note">Координаты и график — демонстрационные данные (см. «Календарный план»).</p>
      )}

      {!dashboard.available && (
        <p className="sk-panel sk-panel--error" style={{ marginTop: "var(--sk-space-3)" }}>
          База данных временно недоступна — сводка показывает нулевые значения, а не выдуманные данные.
        </p>
      )}

      <div className="sk-stat-cards">
        <StatCard
          icon={<CameraStatIcon />}
          value={`${onlineCameraCount}/${cameras.length}`}
          label="Камеры онлайн"
          hint={
            cameras.length === 0
              ? "Камеры не добавлены"
              : onlineCameraCount < cameras.length
                ? `${cameras.length - onlineCameraCount} без трансляции — снимки по расписанию`
                : "Все камеры с трансляцией"
          }
          accent={cameras.length === 0 ? undefined : onlineCameraCount === cameras.length ? "ok" : "warning"}
        />
        <StatCard
          icon={<EquipmentIcon classKey="excavator" />}
          value={dashboard.recognized_equipment_type_count}
          label="Распознано типов техники"
          hint="по последним снимкам камер"
        />
        <StatCard
          icon={<WarningStatIcon />}
          value={openDeviations.length}
          label="Отклонения (требуют внимания)"
          hint={criticalOpenCount > 0 ? `в т.ч. критических: ${criticalOpenCount}` : "критических нет"}
          accent={openDeviations.length === 0 ? "ok" : criticalOpenCount > 0 ? "danger" : "warning"}
        />
        <StatCard
          icon={<ChartStatIcon />}
          value={dashboard.plan_completion_percent !== null ? `${dashboard.plan_completion_percent}%` : "—"}
          label="Выполнение плана"
          hint={dashboard.current_stage?.work_name ?? "Нет активного этапа"}
        />
      </div>

      <div className="sk-dashboard__grid2">
        <div className="sk-dashboard__main2">
          <div className="sk-panel sk-camera-card">
            {cameras.length > 0 && (
              <div className="sk-camera-card__pills">
                {cameras.map((camera) => {
                  const online = Boolean(camera.stream_url);
                  return (
                    <button
                      key={camera.camera_id}
                      type="button"
                      className={`sk-camera-card__pill${
                        camera.camera_id === selectedCameraId ? " sk-camera-card__pill--active" : ""
                      }`}
                      onClick={() => setSelectedCameraId(camera.camera_id)}
                    >
                      <span
                        className={`sk-camera-card__dot${online ? " sk-camera-card__dot--online" : ""}`}
                        title={online ? "в сети" : "пока что не в сети (скринкаст)"}
                      />
                      {camera.name}
                    </button>
                  );
                })}
              </div>
            )}

            {selectedCamera && (
              <div className="sk-camera-card__head">
                <span
                  className={`sk-camera-card__live-dot${
                    selectedCamera.stream_url && !isHistoryMode ? " sk-camera-card__live-dot--on" : ""
                  }`}
                  aria-hidden="true"
                  title={selectedCamera.stream_url && !isHistoryMode ? "В эфире" : "Снимки по расписанию"}
                />
                {displayedObservationSummary && (
                  <span className="sk-camera-card__head-time">
                    {new Date(displayedObservationSummary.created_at).toLocaleString("ru-RU")}
                  </span>
                )}
                {isHistoryMode && <span className="sk-camera-card__history-badge">Архив</span>}
                {cameraHistory && cameraHistory.length > 1 && (
                  <div className="sk-camera-card__history-controls">
                    <button
                      type="button"
                      className="sk-camera-card__history-btn"
                      onClick={() => setHistoryIndex((i) => i + 1)}
                      disabled={!hasOlderHistory}
                      title="Предыдущий снимок"
                    >
                      ‹ Назад
                    </button>
                    <button
                      type="button"
                      className="sk-camera-card__history-btn"
                      onClick={() => setHistoryIndex((i) => Math.max(0, i - 1))}
                      disabled={!isHistoryMode}
                      title="Следующий снимок"
                    >
                      Вперёд ›
                    </button>
                    {isHistoryMode && (
                      <button
                        type="button"
                        className="sk-camera-card__history-btn sk-camera-card__history-btn--live"
                        onClick={() => setHistoryIndex(0)}
                      >
                        Вернуться в онлайн
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="sk-camera-card__frame" ref={setFrameRef}>
              {selectedCamera && displayedObservationSummary ? (
                <>
                  <img
                    className="sk-camera-card__image"
                    src={getObservationImageUrl(projectId, displayedObservationSummary.observation_id)}
                    crossOrigin="use-credentials"
                    alt={
                      isHistoryMode
                        ? `Архивный снимок камеры ${selectedCamera.name}`
                        : `Последний снимок камеры ${selectedCamera.name}`
                    }
                    onLoad={(event) => {
                      const target = event.currentTarget;
                      setImageSize({ width: target.naturalWidth, height: target.naturalHeight });
                    }}
                  />
                  {imageSize &&
                    displayRect &&
                    observation?.detections.map((detection, index) => {
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
                            left: `${displayRect.offsetX + (x1 / naturalWidth) * displayRect.width}px`,
                            top: `${displayRect.offsetY + (y1 / naturalHeight) * displayRect.height}px`,
                            width: `${((x2 - x1) / naturalWidth) * displayRect.width}px`,
                            height: `${((y2 - y1) / naturalHeight) * displayRect.height}px`,
                            borderColor: color,
                          }}
                          title={`${detection.label_ru} ${(detection.confidence * 100).toFixed(0)}%`}
                        >
                          <span className="sk-bbox__label" style={{ backgroundColor: color }}>
                            {detection.label_ru} {(detection.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      );
                    })}

                  {detectedGroups.length > 0 && (
                    <div className="sk-camera-card__legend">
                      <div className="sk-camera-card__legend-title">Обнаружено</div>
                      {detectedGroups.map((g) => (
                        <div key={g.classKey} className="sk-camera-card__legend-item">
                          <span
                            className="sk-camera-card__legend-dot"
                            style={{ background: classColor(g.classKey) }}
                            aria-hidden="true"
                          />
                          <span className="sk-camera-card__legend-label">
                            {g.label}
                            {g.ambiguous && (
                              <sup
                                className="sk-camera-card__legend-unsure"
                                title="Похожий класс техники — уверенность снижена"
                              >
                                ?
                              </sup>
                            )}
                          </span>
                          <b className="sk-camera-card__legend-count">{g.count}</b>
                        </div>
                      ))}
                    </div>
                  )}

                  {topCriticalDeviation && !isHistoryMode && (
                    <div className="sk-camera-card__toast">
                      <div className="sk-camera-card__toast-title">⚠ Нехватка техники</div>
                      {toastShortfalls.length > 0 ? (
                        <ul className="sk-camera-card__toast-list">
                          {toastShortfalls.map((c) => (
                            <li key={c.class_key}>
                              <span>{c.label_ru}</span>
                              <span className="sk-camera-card__toast-count">
                                план {c.required_qty} · факт {c.actual_qty}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="sk-camera-card__toast-message">{topCriticalDeviation.message}</p>
                      )}
                      <div className="sk-camera-card__toast-meta">
                        {topCriticalDeviation.work_name ?? "Этап не указан"} · {topCriticalDeviation.zone_name}
                        {topCriticalDeviation.occurrence_count > 1 && (
                          <> · подтверждено {topCriticalDeviation.occurrence_count} снимками подряд</>
                        )}
                      </div>
                      <Link to={`/projects/${projectId}/notifications`} className="sk-camera-card__toast-link">
                        Подробнее →
                      </Link>
                    </div>
                  )}
                </>
              ) : (
                <div className="sk-camera-card__empty">
                  {cameras.length === 0 ? "В проекте ещё нет камер." : "С этой камеры ещё нет снимков."}
                </div>
              )}
            </div>

            {observationError && (
              <p className="sk-panel--error" style={{ marginTop: "var(--sk-space-2)" }}>
                Не удалось загрузить разбор снимка: {observationError}
              </p>
            )}
          </div>

          <div className="sk-dashboard__secondary-row">
            <div className="sk-panel sk-current-stage">
              <div className="sk-current-stage__head">
                <h2>
                  Текущий этап
                  {isHistoryMode && <span className="sk-current-stage__badge">на дату снимка</span>}
                </h2>
                {!isHistoryMode && dashboard.current_stage && (
                  <span className="sk-current-stage__percent">{dashboard.current_stage.progress_percent}%</span>
                )}
              </div>
              {isHistoryMode ? (
                historyStageInfo ? (
                  <>
                    <div className="sk-current-stage__title">{historyStageInfo.work_name}</div>
                    <div className="sk-progress-bar">
                      <div
                        className="sk-progress-bar__fill"
                        style={{ width: `${historyStageProgressPercent ?? 0}%` }}
                      />
                    </div>
                    <div className="sk-current-stage__meta">
                      {historyStageInfo.start_date} – {historyStageInfo.end_date}
                    </div>
                  </>
                ) : (
                  <p className="sk-empty-state">На эту дату активных этапов не было.</p>
                )
              ) : dashboard.current_stage ? (
                <>
                  <div className="sk-current-stage__title">{dashboard.current_stage.work_name}</div>
                  <div className="sk-progress-bar">
                    <div
                      className="sk-progress-bar__fill"
                      style={{ width: `${dashboard.current_stage.progress_percent}%` }}
                    />
                  </div>
                  <div className="sk-current-stage__meta">
                    {dashboard.current_stage.start_date} – {dashboard.current_stage.end_date}
                  </div>
                </>
              ) : (
                <p className="sk-empty-state">Нет активного этапа графика.</p>
              )}
            </div>

            <div className="sk-panel sk-eq-panel">
              <h2>Техника на площадке</h2>
              <EquipmentMiniGrid checks={quantityChecks} fallbackGroups={detectedGroups} />
            </div>

            <div className="sk-panel sk-deviation-chart-panel">
              <div className="sk-current-stage__head">
                <h2>Динамика отклонений</h2>
                {deviationsByDayTotal > 0 && (
                  <span className="sk-current-stage__percent sk-current-stage__percent--danger">
                    {deviationsByDayTotal}
                  </span>
                )}
              </div>
              {deviationsByDay.length === 0 || deviationsByDay.every((d) => d.value === 0) ? (
                <p className="sk-empty-state">Отклонений не зафиксировано.</p>
              ) : (
                <MiniBarChart data={deviationsByDay} />
              )}
              <Link to={`/projects/${projectId}/analytics`} className="sk-deviation-panel__link">
                Подробная аналитика →
              </Link>
            </div>
          </div>
        </div>

        <div className="sk-dashboard__aside">
          <aside className="sk-panel sk-deviation-panel">
            <div className="sk-deviation-panel__head">
              <h2>Отклонения</h2>
              {recentDeviations.length > 0 && (
                <span className="sk-deviation-panel__badge">{recentDeviations.length}</span>
              )}
              <Link to={`/projects/${projectId}/notifications`} className="sk-deviation-panel__all-link">
                Все
              </Link>
            </div>
            {recentDeviations.length === 0 && <p className="sk-empty-state">Отклонений не зафиксировано.</p>}
            <ul className="sk-deviation-list">
              {recentDeviations.map((item) => (
                <li key={item.id}>
                  <Link
                    to={`/projects/${projectId}/notifications`}
                    className={`sk-deviation-item sk-deviation-item--${item.severity}`}
                  >
                    <div className="sk-deviation-item__top">
                      <span className="sk-deviation-item__severity">
                        {SEVERITY_ICON[item.severity] ?? "•"} {item.severity_label_ru}
                      </span>
                      <span className="sk-deviation-item__time">
                        {new Date(item.detected_at).toLocaleString("ru-RU", {
                          day: "2-digit",
                          month: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </div>
                    <div className="sk-deviation-item__title">{item.title}</div>
                    <div className="sk-deviation-item__sub">
                      {item.work_name ?? "Этап не указан"} · {item.zone_name}
                    </div>
                    <div className="sk-deviation-item__bottom">
                      {item.before_observation_id && (
                        <img
                          className="sk-deviation-item__thumb"
                          src={getObservationImageUrl(projectId, item.before_observation_id)}
                          crossOrigin="use-credentials"
                          alt=""
                          aria-hidden="true"
                        />
                      )}
                      <span className="sk-deviation-item__equipment">
                        {item.equipment.length > 0 ? item.equipment.join(", ") : "—"}
                      </span>
                      <span className="sk-deviation-item__chevron" aria-hidden="true">
                        ›
                      </span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
            <Link to={`/projects/${projectId}/notifications`} className="sk-deviation-panel__link">
              Показать все отклонения →
            </Link>
          </aside>

          <div className="sk-panel sk-map-panel">
            <div className="sk-map-panel__head">
              <h2>Карта площадки</h2>
              <Link to={`/projects/${projectId}/map`} className="sk-map-panel__link">
                Открыть карту →
              </Link>
            </div>
            <MiniSiteMap features={site.geojson.features} zoneStatus={zoneStatus} center={mapCenter} />
          </div>
        </div>
      </div>
    </div>
  );
}
