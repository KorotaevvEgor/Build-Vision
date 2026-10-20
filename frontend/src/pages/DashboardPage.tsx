import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  fetchScheduleNetwork,
  fetchCamera,
  fetchDashboard,
  fetchDeviations,
  fetchWeatherRisks,
  type WeatherRiskResponse,
  fetchObservation,
  fetchSite,
  fetchZoneStagesOnDate,
  getObservationImageUrl,
  type ScheduleNetworkResponse,
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
import { DashboardGantt } from "../components/DashboardGantt";
import { MiniSiteMap } from "../components/MiniSiteMap";
import { getDashboardDetections } from "../components/dashboardMarkup";
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
  drilling_rig: "#b794f6",
  crawler_crane: "#38bdf8",
  wheeled_excavator: "#fbbf24",
  backhoe_loader: "#fb923c",
};

function classColor(classKey: string): string {
  return CLASS_COLOR_VARS[classKey] ?? "var(--sk-class-unknown)";
}

const OPEN_STATUSES = new Set(["detected", "assigned"]);

function StatCard({
  value,
  label,
  hint,
  accent,
}: {
  value: ReactNode;
  label: string;
  hint?: string;
  accent?: "ok" | "warning" | "danger";
}) {
  return (
    <div className="sk-panel sk-stat-card">
      <div className="sk-stat-card__copy">
        <div className="sk-stat-card__label">{label}</div>
        {hint && (
          <div title={hint} className={`sk-stat-card__hint${accent ? ` sk-stat-card__hint--${accent}` : ""}`}>{hint}</div>
        )}
      </div>
      <div className={`sk-stat-card__value${accent === "danger" ? " sk-stat-card__value--danger" : ""}`}>{value}</div>
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
            <div className="sk-eq__count">
              <strong>{q.actual_qty}</strong><span> / {q.required_qty}</span>
            </div>
            <div className="sk-eq__label">{q.label_ru}</div>
            <div className="sk-eq__status">{q.satisfied ? "В наличии" : `Не хватает ${q.required_qty - q.actual_qty}`}</div>
            <div className="sk-eq__caption">На фото / по плану</div>
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
  const isPaused = project.status === "paused";
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [site, setSite] = useState<SiteResponse | null>(null);
  const [deviations, setDeviations] = useState<DeviationRecord[] | null>(null);
  const [scheduleNetwork, setScheduleNetwork] = useState<ScheduleNetworkResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [weatherRisks, setWeatherRisks] = useState<WeatherRiskResponse | null>(null);
  const [deviationIndex, setDeviationIndex] = useState(0);
  const deviationListRef = useRef<HTMLUListElement | null>(null);
  const deviationWheelCleanup = useRef<(() => void) | null>(null);
  const setDeviationListRef = useCallback((element: HTMLUListElement | null) => {
    deviationWheelCleanup.current?.();
    deviationListRef.current = element;
    if (!element) return;
    element.scrollTop = 0;
    setDeviationIndex(0);
    let lastStep = 0;
    const wheel = (event: WheelEvent) => {
      if (element.scrollHeight <= element.clientHeight + 1 || !event.deltaY) return;
      event.preventDefault();
      const now = performance.now();
      if (now - lastStep < 350) return;
      lastStep = now;
      element.scrollBy({ top: Math.sign(event.deltaY) * (element.clientHeight + 12), behavior: "smooth" });
    };
    element.addEventListener("wheel", wheel, { passive: false });
    deviationWheelCleanup.current = () => element.removeEventListener("wheel", wheel);
  }, []);
  useEffect(() => () => deviationWheelCleanup.current?.(), []);


  const [selectedCameraId, setSelectedCameraId] = useState<string>("");
  const [observation, setObservation] = useState<ObservationDetail | null>(null);
  const [observationError, setObservationError] = useState<string | null>(null);
  const [loadedImage, setLoadedImage] = useState<{ id:string; width:number; height:number } | null>(null);
  const [imageErrorId,setImageErrorId] = useState<string|null>(null);
  const [imageAttempt,setImageAttempt] = useState(0);
  const [equipmentHover, setEquipmentHover] = useState<{ observationId: string; classKey: string } | null>(null);
  // История снимков камеры для прокрутки назад с Главной: cameraHistory[0] — самый
  // свежий снимок ("онлайн"), historyIndex > 0 — режим просмотра истории.
  const [cameraHistory, setCameraHistory] = useState<ObservationSummary[] | null>(null);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [historyStageInfo, setHistoryStageInfo] = useState<ZoneStageOnDate | null>(null);
  const [historyStageLoadedId,setHistoryStageLoadedId]=useState<string|null>(null);
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
    setWeatherRisks(null);
    setDeviationIndex(0);
    setScheduleNetwork(null);
    setError(null);
    setSelectedCameraId("");

    fetchDashboard(projectId)
      .then((d) => {
        if (cancelled) return;
        setDashboard(d);
        if (d.cameras.length > 0) setSelectedCameraId(d.cameras[0].camera_id);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    fetchWeatherRisks(projectId).then(data => !cancelled && setWeatherRisks(data)).catch(() => {});
    fetchSite(projectId).then(s=>!cancelled&&setSite(s)).catch(()=>{});

    // Отклонения и аналитика грузятся отдельно и не блокируют экран.
    fetchDeviations(projectId)
      .then((data) => !cancelled && setDeviations(data.items))
      .catch(() => !cancelled && setDeviations([]));
    fetchScheduleNetwork(projectId)
      .then(data => !cancelled && setScheduleNetwork(data))
      .catch(() => !cancelled && setScheduleNetwork(null));

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
  const activeObservation = observation?.observation_id === selectedObservationId ? observation : null;
  const imageSize = loadedImage?.id===selectedObservationId ? loadedImage : null;
  const aiMarkupAvailable = Boolean(activeObservation?.ai_equipment?.available);
  const highlightedClass = equipmentHover?.observationId === selectedObservationId ? equipmentHover.classKey : null;
  const visualDetections = useMemo(() => getDashboardDetections(activeObservation, imageSize ?? {width:1,height:1}), [activeObservation, imageSize]);

  useEffect(()=>{
    if(!selectedObservationId||imageSize)return;
    const timer=window.setTimeout(()=>setImageErrorId(selectedObservationId),20000);
    return ()=>window.clearTimeout(timer);
  },[selectedObservationId,imageSize,imageAttempt]);

  // Полный разбор (детекции + план/факт по этапу) грузится под выбранный снимок отдельно:
  // сводка `/dashboard`/`/cameras/{id}` отдаёт только статус, без списка объектов.
  useEffect(() => {
    let cancelled = false;
    setObservation(null);
    setObservationError(null);
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
    setHistoryStageLoadedId(null);
    if (!isHistoryMode || !selectedCamera || !displayedObservationSummary) return;
    const onDate = displayedObservationSummary.observed_date ?? displayedObservationSummary.created_at.slice(0, 10);
    fetchZoneStagesOnDate(projectId, selectedCamera.zone_id, onDate)
      .then((data) => !cancelled && setHistoryStageInfo(data.stages[0] ?? null))
      .catch(() => !cancelled && setHistoryStageInfo(null))
      .finally(()=>!cancelled&&setHistoryStageLoadedId(displayedObservationSummary.observation_id));
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
    for (const d of visualDetections) {
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
  }, [visualDetections]);

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

  const quantityChecks = (matchedStage?.quantity_checks ?? []).map((q) => {
    if (!aiMarkupAvailable) return q;
    const actual = detectedGroups.find((g) => g.classKey === q.class_key)?.count ?? 0;
    return { ...q, actual_qty: actual, satisfied: actual >= q.required_qty };
  });

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
  if (!dashboard) {
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

  const currentFinding = [...openDeviations].sort((a, b) =>
    Number(b.kind === "quantity_shortfall" && b.before_observation_id === selectedObservationId) -
    Number(a.kind === "quantity_shortfall" && a.before_observation_id === selectedObservationId) ||
    new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime()
  )[0];
  const weatherPeriod = !weatherRisks?.is_stale ? weatherRisks?.risk_periods[0] : undefined;
  const weatherFinding: DeviationRecord = {
    id: -1, kind: "weather_risk", kind_label_ru: "Погодный риск", severity: "info", severity_label_ru: "К сведению",
    status: "detected", status_label_ru: weatherPeriod ? "Потенциальный риск · прогноз" : "Потенциальный сценарий",
    title: weatherPeriod ? "Погодные ограничения могут повлиять на работы" : "Потенциальная погодная пауза",
    message: weatherPeriod ? weatherPeriod.message : "Осадки, усиление ветра или похолодание могут потребовать корректировки порядка работ. Это сценарий для контроля, а не выявленная задержка.",
    equipment: [], zone_id: "", zone_name: "Площадка", stage_id: weatherPeriod?.stage_id ?? dashboard.current_stage?.stage_id ?? null,
    work_name: weatherPeriod?.work_name ?? dashboard.current_stage?.work_name ?? null,
    is_on_critical_path: false, occurrence_count: 0, auto_resolved: false, resolution_note: "", assignee: null, assignee_id: null,
    before_observation_id: null, after_observation_id: null, detected_at: weatherRisks?.fetched_at ?? "", resolved_at: null, confirmed_at: null,
  };
  const recentDeviations = [...(currentFinding ? [currentFinding] : []), weatherFinding];

  const onlineCameraCount = cameras.filter((c) => c.stream_online).length;

  return (
    <div className="sk-dashboard">
      {site?.schedule_is_demo && (
        <p className="sk-demo-note">Координаты и график — демонстрационные данные (см. «Календарный план»).</p>
      )}

      {!dashboard.available && (
        <p className="sk-panel sk-panel--error" style={{ marginTop: "var(--sk-space-3)" }}>
          База данных временно недоступна — сводка показывает нулевые значения, а не выдуманные данные.
        </p>
      )}

      <div className="sk-dashboard__overview">
            <div className="sk-panel sk-current-stage">
              <div className="sk-current-stage__head">
                <h2>
                  Текущий этап
                  {isHistoryMode && <span className="sk-current-stage__badge">на дату снимка</span>}
                </h2>
                {!isHistoryMode && dashboard.current_stage && (
                  <span className={`sk-current-stage__percent${isPaused ? " sk-current-stage__percent--paused" : ""}`}>{isPaused ? "Приостановлен" : dashboard.current_stage.progress_percent===null?"Нет замера":`${dashboard.current_stage.progress_percent??0}%`}</span>
                )}
              </div>
              {isHistoryMode ? (
                historyStageLoadedId!==selectedObservationId ? <p className="sk-empty-state">Загрузка этапа на дату снимка…</p> : historyStageInfo ? (
                  <>
                    <div className="sk-current-stage__title">{historyStageInfo.work_name}</div>
                    <div className="sk-progress-bar">
                      <div
                        className="sk-progress-bar__fill"
                        style={{ width: `${historyStageProgressPercent ?? 0}%` }}
                      />
                    </div>
                    <div className="sk-current-stage__meta">
                      <div><span>Начало</span><strong>{historyStageInfo.start_date.split("-").reverse().join(".")}</strong></div>
                      <div><span>Завершение</span><strong>{historyStageInfo.end_date.split("-").reverse().join(".")}</strong></div>
                    </div>
                  </>
                ) : (
                  <p className="sk-empty-state">На эту дату активных этапов не было.</p>
                )
              ) : dashboard.current_stage ? (
                <>
                  <div className="sk-current-stage__title">{dashboard.current_stage.work_name}</div>
                  {!isPaused && <div className="sk-progress-bar">
                    <div
                      className="sk-progress-bar__fill"
                      style={{ width: `${dashboard.current_stage.progress_percent??0}%` }}
                    />
                  </div>}
                  <div className="sk-current-stage__meta">
                    <div><span>Начало</span><strong>{dashboard.current_stage.start_date.split("-").reverse().join(".")}</strong></div>
                      <div><span>Завершение</span><strong>{dashboard.current_stage.end_date.split("-").reverse().join(".")}</strong></div>
                  </div>
                  {isPaused && <p className="sk-current-stage__paused-note">Последний этап по фото. Срок сдачи — приостановлено.</p>}
                </>
              ) : (
                <p className="sk-empty-state">Нет активного этапа графика.</p>
              )}
            </div>

            <div className="sk-panel sk-eq-panel">
              <h2>Техника на площадке</h2>
              <p className="sk-table__muted">По выбранному снимку</p>
              {selectedObservationId&&!activeObservation ? <p className="sk-empty-state">{observationError ? "Разбор кадра недоступен" : "Загрузка разбора кадра…"}</p> : <EquipmentMiniGrid checks={quantityChecks} fallbackGroups={detectedGroups} />}
            </div>
      <div className="sk-stat-cards">
        <StatCard
          value={<>{onlineCameraCount}<small> / {cameras.length}</small></>}
          label="Камеры онлайн"
          hint={
            cameras.length === 0
              ? "Камеры не добавлены"
              : onlineCameraCount < cameras.length
                ? "Фото по расписанию"
                : "Все камеры с трансляцией"
          }
          accent={cameras.length === 0 ? undefined : onlineCameraCount === cameras.length ? "ok" : "warning"}
        />
        <StatCard
          value={selectedObservationId&&!activeObservation ? "…" : aiMarkupAvailable ? detectedGroups.length : dashboard.recognized_equipment_type_count}
          label="Типы техники"
          hint={aiMarkupAvailable ? "по разметке выбранного кадра" : "по последним снимкам камер"}
        />
        <StatCard
          value={openDeviations.length}
          label="Открытые отклонения"
          hint={criticalOpenCount > 0 ? `Критических: ${criticalOpenCount}` : "Критических нет"}
          accent={openDeviations.length === 0 ? "ok" : criticalOpenCount > 0 ? "danger" : "warning"}
        />
        <StatCard
          value={dashboard.plan_completion_percent !== null ? <>{dashboard.plan_completion_percent.toLocaleString("ru-RU")}<small>%</small></> : "—"}
          label="Готовность этапа"
          hint={dashboard.plan_completion_percent===null?"Нужен подтверждённый замер":dashboard.current_stage?.work_name??"Нет активного этапа"}
        />
      </div>
      </div>

      <div className="sk-dashboard__grid2">
        <div className="sk-dashboard__main2">
          <div className="sk-panel sk-camera-card">
            <div className="sk-camera-card__toolbar">
              {cameras.length > 0 && (
                <div className="sk-camera-card__pills">
                  {cameras.map((camera) => {
                    const online = Boolean(camera.stream_online);
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
                <>
                  {displayedObservationSummary && (
                    <span className="sk-camera-card__head-time">
                      {new Date(displayedObservationSummary.observed_date ?? displayedObservationSummary.created_at).toLocaleDateString("ru-RU")}
                    </span>
                  )}
                  {isHistoryMode && <span className="sk-camera-card__history-badge">Архив</span>}
                  {cameraHistory && cameraHistory.length > 1 && (
                    <div className="sk-camera-card__history-controls">
                      <span className="sk-camera-card__frame-counter" aria-live="polite">Кадр {historyIndex + 1} / {cameraHistory.length}</span>
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
                </>
              )}
            </div>

            <div
              className="sk-camera-card__frame"
              ref={setFrameRef}
              style={{ aspectRatio: imageSize ? `${imageSize.width} / ${imageSize.height}` : "16 / 9" }}
            >
              {selectedCamera && displayedObservationSummary ? (
                <>
                  <img
                    key={`${selectedObservationId}:${imageAttempt}`}
                    className="sk-camera-card__image"
                    src={`${getObservationImageUrl(projectId, displayedObservationSummary.observation_id)}${imageAttempt ? `&retry=${imageAttempt}` : ""}`}
                    decoding="async"
                    fetchPriority="high"
                    crossOrigin="use-credentials"
                    alt={
                      isHistoryMode
                        ? `Архивный снимок камеры ${selectedCamera.name}`
                        : `Последний снимок камеры ${selectedCamera.name}`
                    }
                    onLoad={(event) => {
                      const target = event.currentTarget;
                      setLoadedImage({ id:displayedObservationSummary.observation_id, width: target.naturalWidth, height: target.naturalHeight });
                      setImageErrorId(null);
                    }}
                    onError={()=>setImageErrorId(displayedObservationSummary.observation_id)}
                  />
                  {!imageSize && <div className="sk-camera-image-status" role="status">
                    {imageErrorId===selectedObservationId ? <><span>Не удалось загрузить фото</span><button type="button" onClick={()=>{setImageErrorId(null);setImageAttempt(i=>i+1);}}>Повторить загрузку</button></> : <span>Загрузка фотографии…</span>}
                  </div>}
                  {imageSize &&
                    displayRect &&
                    visualDetections.map((detection, index) => {
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
                          className={`sk-bbox${aiMarkupAvailable ? " sk-bbox--ai" : ""}${highlightedClass && highlightedClass !== detection.class_key ? " sk-bbox--dim" : ""}${highlightedClass === detection.class_key ? " sk-bbox--active" : ""}${detection.ambiguous ? " sk-bbox--ambiguous" : ""}${
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
                          onMouseEnter={() => setEquipmentHover({ observationId: selectedObservationId!, classKey: detection.class_key })}
                          onMouseLeave={() => setEquipmentHover(null)}
                        >
                          <span className={`sk-bbox__label${y1 / naturalHeight < 0.07 ? " sk-bbox__label--inside" : ""}`} style={{ backgroundColor: color }}>
                            {detection.label_ru} {(detection.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      );
                    })}


                  {aiMarkupAvailable && detectedGroups.length === 0 && <span className="sk-camera-card__ai-empty">Техника на этом кадре не обнаружена</span>}
                  <div className="sk-camera-card__overlays">
                  {topCriticalDeviation && !isHistoryMode && !aiMarkupAvailable && activeObservation && imageSize && (
                    <details key={`${selectedObservationId}:${topCriticalDeviation.id}`} className="sk-camera-card__toast">
                      <summary className="sk-camera-card__toast-title">Нехватка техники</summary>
                      <div className="sk-camera-card__toast-body">
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
                    </details>
                  )}
                  {detectedGroups.length > 0 && (
                    <div className="sk-camera-card__legend">
                      <div className="sk-camera-card__legend-title">Техника на кадре</div>
                      {detectedGroups.map((g) => (
                        <button type="button" key={g.classKey} className={`sk-camera-card__legend-item${highlightedClass === g.classKey ? " sk-camera-card__legend-item--active" : ""}`}
                          onMouseEnter={() => setEquipmentHover({ observationId: selectedObservationId!, classKey: g.classKey })}
                          onMouseLeave={() => setEquipmentHover(null)}
                          onFocus={() => setEquipmentHover({ observationId: selectedObservationId!, classKey: g.classKey })}
                          onBlur={() => setEquipmentHover(null)}>
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
                        </button>
                      ))}
                    </div>
                  )}
                  </div>
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
            <div className="sk-panel sk-dashboard-schedule">
              <div className="sk-dashboard-schedule__head"><h2>Календарный план</h2><Link to={`/projects/${projectId}/schedule`}>Открыть полностью ↗</Link></div>
              {scheduleNetwork?.stages.length ? <DashboardGantt stages={scheduleNetwork.stages} currentStageId={dashboard.current_stage?.stage_id} paused={isPaused} /> : <p className="sk-empty-state">{scheduleNetwork ? "Календарный план пока не заполнен." : "План загружается. Полная версия доступна по ссылке выше."}</p>}
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
            <ul key={`${projectId}:${currentFinding?.id ?? "loading"}`} className="sk-deviation-list" ref={setDeviationListRef} tabIndex={0} aria-label="Карточки отклонений. Прокрутка переключает карточку"
              onScroll={(event) => setDeviationIndex(Math.min(recentDeviations.length - 1, Math.max(0, Math.round(event.currentTarget.scrollTop / (event.currentTarget.clientHeight + 12)))))}>

              {recentDeviations.map((item) => {
                const shortfall = item.kind === "quantity_shortfall" && item.before_observation_id === selectedObservationId && item.stage_id === matchedStage?.stage_id
                  ? quantityChecks.find((q) => !q.satisfied && (item.equipment.includes(q.label_ru) || item.equipment.includes(q.class_key))) : undefined;
                const needsEquipmentCheck = ["quantity_shortfall", "missing_equipment"].includes(item.kind);
                return (
                <li key={item.id}>
                  <Link
                    to={`/projects/${projectId}/${item.kind === "weather_risk" ? "forecast" : `notifications/${item.id}`}`}
                    className={`sk-deviation-item sk-deviation-item--${item.severity}`}
                  >
                    <div className="sk-deviation-item__top">
                      <span className="sk-deviation-item__severity">
                        {item.severity_label_ru}
                      </span>
                      <span className="sk-deviation-item__status">{item.status_label_ru}</span>
                      <span className="sk-deviation-item__time">
                        {item.detected_at ? new Date(item.detected_at).toLocaleString("ru-RU", {
                          day: "2-digit",
                          month: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        }) : "Прогноз"}
                      </span>
                    </div>
                    <div className="sk-deviation-item__title">{item.title}</div>
                    <p className="sk-deviation-item__fact">{item.message}</p>
                    {shortfall && <div className="sk-deviation-item__quantities" aria-label="Сравнение количества техники">
                      <div><span>По плану</span><strong>{shortfall.required_qty}</strong></div>
                      <div><span>На снимке</span><strong>{shortfall.actual_qty}</strong></div>
                      <div className="sk-deviation-item__deficit"><span>Не хватает</span><strong>{shortfall.required_qty - shortfall.actual_qty}</strong></div>
                    </div>}
                    {item.kind === "weather_risk" && <>
                      <div className="sk-deviation-item__weather-note"><strong>{weatherPeriod ? "Условие по прогнозу" : weatherRisks?.status === "ok" && !weatherRisks.is_stale ? "Прогноз не подтверждает превышение порогов" : "Актуальные погодные риски не подтверждены"}</strong><p>{weatherPeriod ? `Ожидается ${weatherPeriod.peak_value} ${weatherPeriod.units}; порог правила — ${weatherPeriod.threshold} ${weatherPeriod.units}.` : "Погодный сценарий не учитывается как открытое нарушение. Факт остановки работ не установлен."}</p></div>
                      <div className="sk-deviation-item__check sk-deviation-item__check--weather"><span>Что проверить</span><p>Перед сменой сверить прогноз и ограничения для подъёмных и бетонных работ с регламентом площадки.</p></div>
                    </>}
                    {needsEquipmentCheck && <div className="sk-deviation-item__check"><span>Что проверить</span><p>Уточнить наличие техники за пределами обзора камеры и её участие в работах этапа.</p></div>}
                    <div className="sk-deviation-item__evidence">{item.kind === "weather_risk" ? "Погодный контроль · потенциальное влияние на график" : <>По {item.occurrence_count === 1 ? "одному снимку" : `${item.occurrence_count} снимкам`}{item.is_on_critical_path ? " · Этап на критическом пути" : ""}</>}</div>
                    <div className="sk-deviation-item__sub">
                      <span>Этап</span> {item.work_name ?? "Не указан"}<br /><span>Зона</span> {item.zone_name}
                    </div>
                    <div className="sk-deviation-item__bottom">
                      {item.before_observation_id && (
                        <img
                          className="sk-deviation-item__thumb"
                          src={getObservationImageUrl(projectId, item.before_observation_id)}
                          crossOrigin="use-credentials"
                          loading="lazy"
                          decoding="async"
                          alt=""
                          aria-hidden="true"
                        />
                      )}
                      <span className="sk-deviation-item__equipment" title={`${item.work_name ?? "Этап не указан"} · ${item.zone_name}`}>
                        <strong>{item.kind === "weather_risk" ? "Прогноз и факторы риска" : "Снимок и подробности"}</strong>
                        <span>{item.work_name ?? item.zone_name}</span>
                      </span>
                      <span className="sk-deviation-item__chevron" aria-hidden="true">
                        ›
                      </span>
                    </div>
                  </Link>
                </li>
              );})}
            </ul>
            <div className="sk-deviation-navigation" aria-label="Переключение карточек">
              <button type="button" aria-label="Предыдущее отклонение" disabled={deviationIndex === 0} onClick={() => { const list = deviationListRef.current; if (list) list.scrollBy({ top: -(list.clientHeight + 12), behavior: "smooth" }); }}>←</button>
              <span aria-live="polite">{deviationIndex + 1} / {recentDeviations.length}</span>
              <button type="button" aria-label="Следующее отклонение" disabled={deviationIndex >= recentDeviations.length - 1} onClick={() => { const list = deviationListRef.current; if (list) list.scrollBy({ top: list.clientHeight + 12, behavior: "smooth" }); }}>→</button>
              <Link to={`/projects/${projectId}/notifications`}>Все отклонения</Link>
            </div>
          </aside>

          <div className="sk-panel sk-map-panel">
            <div className="sk-map-panel__head">
              <h2>Карта площадки</h2>
              <Link to={`/projects/${projectId}/map`} className="sk-map-panel__link">
                Открыть карту →
              </Link>
            </div>
            {site ? <MiniSiteMap features={site.geojson.features} zoneStatus={zoneStatus} center={mapCenter} /> : <p className="sk-empty-state">Карта пока недоступна. Остальные данные проекта доступны.</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
