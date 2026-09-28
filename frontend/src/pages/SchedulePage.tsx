import { useEffect, useMemo, useState } from "react";
import {
  createStage,
  deleteStage,
  fetchDashboard,
  fetchObservation,
  fetchProjectEvents,
  fetchReadiness,
  fetchRules,
  fetchScheduleNetwork,
  fetchStageForecast,
  fetchStages,
  fetchVocabulary,
  fetchWeatherRisks,
  fetchZones,
  updateStage,
  type DashboardResponse,
  type ForecastResponse,
  type NetworkStage,
  type ObservationDetail,
  type ProjectEventItem,
  type ReadinessResponse,
  type RiskFactor,
  type RulesResponse,
  type ScheduleNetworkResponse,
  type StageDetail,
  type StageWritePayload,
  type VocabularyClassSummary,
  type WeatherRiskResponse,
  type ZoneDetail,
} from "../api";
import { useAuth } from "../AuthContext";
import { useProject } from "../ProjectContext";
import { StatusBadge } from "../components/StatusBadge";
import { EquipmentIcon } from "../components/EquipmentIcons";
import { WeatherRiskPanel } from "../components/WeatherRiskPanel";
import { ProjectDynamicsChart, type DynamicsPoint } from "../components/ProjectDynamicsChart";
import { DelayFactorsDonut } from "../components/DelayFactorsDonut";
import { StageEditForm } from "../components/StageEditForm";
import "./SchedulePage.css";

const RISK_KEY_LABEL: Record<string, string> = {
  missing_equipment: "Недостаток техники",
  pace_decline: "Темп работ",
  weather: "Погода",
  deviation_history: "История отклонений",
  insufficient_data: "Данные",
};

const SEVERITY_LABEL: Record<RiskFactor["severity"], string> = {
  high: "Высокое",
  medium: "Среднее",
  low: "Низкое",
};

const SEVERITY_ACCENT: Record<RiskFactor["severity"], "danger" | "warning" | "ok"> = {
  high: "danger",
  medium: "warning",
  low: "ok",
};

function dayDiff(a: Date, b: Date): number {
  return Math.round((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24));
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function formatShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}

/** Склонение дней: 1 день, 2 дня, 5 дней. */
function plural(days: number): string {
  const n = Math.abs(days) % 100;
  const last = n % 10;
  if (n > 10 && n < 20) return "дней";
  if (last === 1) return "день";
  if (last >= 2 && last <= 4) return "дня";
  return "дней";
}

/** Честная эвристика: доля прошедших дней планового периода этапа (не физический прогресс). */
function timeProgressPercent(stage: NetworkStage, today: Date): number {
  const start = new Date(stage.planned_start_date);
  const end = new Date(stage.planned_end_date);
  const totalDays = dayDiff(start, end) + 1;
  if (totalDays <= 0) return 100;
  const clamped = today < start ? start : today > end ? end : today;
  const elapsed = dayDiff(start, clamped) + 1;
  return Math.round(Math.max(0, Math.min(1, elapsed / totalDays)) * 100);
}

const STATE_COLOR: Record<string, string> = {
  done_on_time: "var(--sk-status-ok)",
  started_early: "var(--sk-status-ok)",
  in_progress: "var(--sk-accent)",
  overdue: "var(--sk-status-danger)",
  unverified: "var(--sk-status-warning)",
  not_started: "var(--sk-text-faint)",
};

function stateColor(state: string): string {
  return STATE_COLOR[state] ?? "var(--sk-text-faint)";
}

/** Проходит по датам плана и строит сегменты месяцев для шапки диаграммы — без сторонних библиотек дат. */
function monthSegments(range: { start: Date; end: Date }): { label: string; days: number }[] {
  const months: { label: string; days: number }[] = [];
  let cursor = new Date(range.start.getFullYear(), range.start.getMonth(), 1);
  const rangeEndExclusive = new Date(range.end.getTime() + 86_400_000);
  while (cursor.getTime() < rangeEndExclusive.getTime()) {
    const nextMonth = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
    const segStart = cursor.getTime() > range.start.getTime() ? cursor : range.start;
    const segEndExclusive = nextMonth.getTime() < rangeEndExclusive.getTime() ? nextMonth : rangeEndExclusive;
    const days = Math.max(1, Math.round((segEndExclusive.getTime() - segStart.getTime()) / 86_400_000));
    const label = cursor.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
    months.push({ label: label.charAt(0).toUpperCase() + label.slice(1), days });
    cursor = nextMonth;
  }
  return months;
}

const STAGE_KPI_LABELS = ["Всего этапов", "Выполнено", "В работе", "Требуют внимания"] as const;

export function SchedulePage() {
  const { projectId } = useProject();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [rules, setRules] = useState<RulesResponse | null>(null);
  const [network, setNetwork] = useState<ScheduleNetworkResponse | null>(null);
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [events, setEvents] = useState<ProjectEventItem[] | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [stageForecast, setStageForecast] = useState<ForecastResponse | null>(null);
  const [weatherRisks, setWeatherRisks] = useState<WeatherRiskResponse | null>(null);
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);
  const [selectedObservation, setSelectedObservation] = useState<ObservationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"gantt" | "list">("gantt");
  const [detailTab, setDetailTab] = useState<"overview" | "equipment" | "edit">("overview");

  // --- Режим редактирования календарного плана (только админ) ---
  const [scheduleEditMode, setScheduleEditMode] = useState(false);
  const [zonesForEdit, setZonesForEdit] = useState<ZoneDetail[] | null>(null);
  const [vocabulary, setVocabulary] = useState<VocabularyClassSummary[] | null>(null);
  const [stagesDetail, setStagesDetail] = useState<StageDetail[] | null>(null);
  const [creatingStage, setCreatingStage] = useState(false);
  const [savingStage, setSavingStage] = useState(false);
  const [stageFormError, setStageFormError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRules(null);
    setNetwork(null);
    setDashboard(null);
    setSelectedStageId(null);
    Promise.all([fetchRules(projectId), fetchScheduleNetwork(projectId), fetchDashboard(projectId)])
      .then(([r, n, d]) => {
        if (cancelled) return;
        setRules(r);
        setNetwork(n);
        setDashboard(d);
        // По умолчанию выбираем работу, которая реально требует внимания.
        const firstLeaf = n.stages.find((s) => !s.is_summary && s.shifts_project_finish)
          ?? n.stages.find((s) => !s.is_summary);
        if (firstLeaf) setSelectedStageId(firstLeaf.stage_id);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    fetchProjectEvents(projectId, 40)
      .then((e) => !cancelled && setEvents(e.items))
      .catch(() => !cancelled && setEvents([]));
    fetchReadiness(projectId)
      .then((r) => !cancelled && setReadiness(r))
      .catch(() => !cancelled && setReadiness(null));
    fetchStageForecast(projectId)
      .then((f) => !cancelled && setStageForecast(f))
      .catch(() => !cancelled && setStageForecast(null));
    fetchWeatherRisks(projectId)
      .then((w) => !cancelled && setWeatherRisks(w))
      .catch(() => !cancelled && setWeatherRisks(null));
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const selectedStage = network?.stages.find((s) => s.stage_id === selectedStageId) ?? null;

  useEffect(() => {
    setDetailTab("overview");
  }, [selectedStageId]);

  useEffect(() => {
    if (!selectedStage || !dashboard) {
      setSelectedObservation(null);
      return;
    }
    const zoneSummary = dashboard.zones.find((z) => z.zone_id === selectedStage.zone_id);
    const obsId = zoneSummary?.latest_observation?.observation_id;
    if (!obsId) {
      setSelectedObservation(null);
      return;
    }
    let cancelled = false;
    fetchObservation(projectId, obsId)
      .then((data) => {
        if (!cancelled) setSelectedObservation(data);
      })
      .catch(() => {
        if (!cancelled) setSelectedObservation(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, selectedStage, dashboard]);

  useEffect(() => {
    if (!scheduleEditMode || !isAdmin) return;
    let cancelled = false;
    Promise.all([fetchZones(projectId), fetchVocabulary(), fetchStages(projectId)])
      .then(([z, v, s]) => {
        if (cancelled) return;
        setZonesForEdit(z.zones);
        setVocabulary(v.classes);
        setStagesDetail(s.stages);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [scheduleEditMode, isAdmin, projectId]);

  const reloadAfterStageChange = async () => {
    const [n, s] = await Promise.all([fetchScheduleNetwork(projectId), fetchStages(projectId)]);
    setNetwork(n);
    setStagesDetail(s.stages);
  };

  const startCreateStage = () => {
    setCreatingStage(true);
    setStageFormError(null);
  };

  const cancelStageForm = () => {
    setCreatingStage(false);
    setStageFormError(null);
    setDetailTab("overview");
  };

  const submitCreateStage = async (payload: StageWritePayload) => {
    setSavingStage(true);
    setStageFormError(null);
    try {
      const { stage } = await createStage(projectId, payload);
      await reloadAfterStageChange();
      setCreatingStage(false);
      setSelectedStageId(stage.stage_id);
    } catch (err) {
      setStageFormError(err instanceof Error ? err.message : "Не удалось создать этап");
    } finally {
      setSavingStage(false);
    }
  };

  const submitEditStage = async (stageId: string, payload: StageWritePayload) => {
    setSavingStage(true);
    setStageFormError(null);
    try {
      await updateStage(projectId, stageId, payload);
      await reloadAfterStageChange();
      setDetailTab("overview");
    } catch (err) {
      setStageFormError(err instanceof Error ? err.message : "Не удалось сохранить этап");
    } finally {
      setSavingStage(false);
    }
  };

  const confirmDeleteStage = async (stageId: string) => {
    setSavingStage(true);
    setStageFormError(null);
    try {
      await deleteStage(projectId, stageId);
      setSelectedStageId(null);
      await reloadAfterStageChange();
      setDetailTab("overview");
    } catch (err) {
      setStageFormError(err instanceof Error ? err.message : "Не удалось удалить этап");
    } finally {
      setSavingStage(false);
    }
  };

  // Диаграмма строится по прогнозным срокам тоже, поэтому шкала должна вмещать
  // и плановые, и прогнозные даты — иначе просроченная работа уехала бы за край.
  const timelineRange = useMemo(() => {
    if (!network || network.stages.length === 0) return null;
    const starts = network.stages.map((s) => new Date(s.planned_start_date).getTime());
    const ends = network.stages.flatMap((s) => [
      new Date(s.planned_end_date).getTime(),
      new Date(s.projected_finish_date).getTime(),
    ]);
    return { start: new Date(Math.min(...starts)), end: new Date(Math.max(...ends)) };
  }, [network]);

  const months = useMemo(() => (timelineRange ? monthSegments(timelineRange) : []), [timelineRange]);

  // Иерархическая нумерация разделов (1., 2., …) и вложенных работ (1.1, 1.2, …) — как в макете.
  // Стадии уже приходят от бэкенда в порядке обхода дерева (родитель перед детьми), поэтому
  // достаточно одного прохода; у проектов без иерархии это просто сквозная нумерация 1, 2, 3…
  const stageNumbers = useMemo(() => {
    const numbers = new Map<string, string>();
    if (!network) return numbers;
    let rootCounter = 0;
    const childCounters = new Map<string, number>();
    for (const stage of network.stages) {
      if (!stage.parent_id || !numbers.has(stage.parent_id)) {
        rootCounter += 1;
        numbers.set(stage.stage_id, String(rootCounter));
      } else {
        const parentNumber = numbers.get(stage.parent_id) as string;
        const nextChild = (childCounters.get(stage.parent_id) ?? 0) + 1;
        childCounters.set(stage.parent_id, nextChild);
        numbers.set(stage.stage_id, `${parentNumber}.${nextChild}`);
      }
    }
    return numbers;
  }, [network]);

  // Динамика проекта: план/факт/прогноз на одной оси времени. Ни одна из трёх линий не выдумана:
  // план считается из реальной длительности этапов базового графика (та же данные, что и у ганта),
  // факт — реальные точки готовности по снимкам (`/readiness`), прогноз — линейная экстраполяция
  // от последней известной точки до 100% к `projected_finish_date` (тот же, что и в вердикте срока сдачи).
  const dynamics = useMemo(() => {
    if (!network || !network.available) return null;
    const leaf = network.stages.filter((s) => !s.is_summary);
    if (leaf.length === 0) return null;
    const sorted = [...leaf].sort(
      (a, b) => new Date(a.planned_start_date).getTime() - new Date(b.planned_start_date).getTime(),
    );
    const totalDuration = sorted.reduce(
      (sum, s) => sum + dayDiff(new Date(s.planned_start_date), new Date(s.planned_end_date)) + 1,
      0,
    );

    const plan: DynamicsPoint[] = [];
    if (totalDuration > 0) {
      let cumulative = 0;
      plan.push({ date: sorted[0].planned_start_date, percent: 0 });
      for (const stage of sorted) {
        const duration = dayDiff(new Date(stage.planned_start_date), new Date(stage.planned_end_date)) + 1;
        plan.push({ date: stage.planned_start_date, percent: Math.round((cumulative / totalDuration) * 1000) / 10 });
        cumulative += duration;
        plan.push({ date: stage.planned_end_date, percent: Math.round((cumulative / totalDuration) * 1000) / 10 });
      }
    }

    const fact: DynamicsPoint[] = (readiness?.fact ?? []).map((p) => ({ date: p.date, percent: p.readiness_percent }));

    const interpolate = (points: DynamicsPoint[], iso: string): number => {
      if (points.length === 0) return 0;
      const t = new Date(iso).getTime();
      if (t <= new Date(points[0].date).getTime()) return points[0].percent;
      for (let i = 0; i < points.length - 1; i++) {
        const a = points[i];
        const b = points[i + 1];
        const ta = new Date(a.date).getTime();
        const tb = new Date(b.date).getTime();
        if (t >= ta && t <= tb) {
          if (tb <= ta) return b.percent;
          return a.percent + (b.percent - a.percent) * ((t - ta) / (tb - ta));
        }
      }
      return points[points.length - 1].percent;
    };

    const todayIso = new Date().toISOString().slice(0, 10);
    const forecastStart: DynamicsPoint =
      fact.length > 0 ? fact[fact.length - 1] : { date: todayIso, percent: interpolate(plan, todayIso) };
    const forecast: DynamicsPoint[] = [];
    if (
      network.projected_finish_date &&
      new Date(network.projected_finish_date).getTime() > new Date(forecastStart.date).getTime()
    ) {
      forecast.push(forecastStart, { date: network.projected_finish_date, percent: 100 });
    }

    return { plan, fact, forecast, today: todayIso };
  }, [network, readiness]);

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить график: {error}</div>;
  }
  if (!rules || !network || !dashboard) {
    return <div className="sk-panel">Загрузка…</div>;
  }

  const today = new Date();
  const totalSpan = timelineRange ? Math.max(dayDiff(timelineRange.start, timelineRange.end), 1) : 1;

  const barPosition = (from: string, to: string) => {
    if (!timelineRange) return { left: 0, width: 0 };
    const start = dayDiff(timelineRange.start, new Date(from));
    const width = Math.max(dayDiff(new Date(from), new Date(to)) + 1, 1);
    return { left: (start / totalSpan) * 100, width: (width / totalSpan) * 100 };
  };

  const todayPosition = timelineRange ? (dayDiff(timelineRange.start, today) / totalSpan) * 100 : 0;

  const dayTickStep = totalSpan > 150 ? 21 : totalSpan > 70 ? 14 : totalSpan > 30 ? 7 : 3;
  const dayTicks = timelineRange
    ? Array.from({ length: Math.floor(totalSpan / dayTickStep) + 1 }, (_, i) => {
        const d = new Date(timelineRange.start.getTime() + i * dayTickStep * 86_400_000);
        return { left: ((i * dayTickStep) / totalSpan) * 100, label: d.toLocaleDateString("ru-RU", { day: "2-digit" }) };
      })
    : [];

  const zoneName = (zoneId: string) => dashboard.zones.find((z) => z.zone_id === zoneId)?.name ?? zoneId;

  const stageQuantityChecks = selectedObservation?.stages.find((s) => s.stage_id === selectedStageId)
    ?.quantity_checks;
  const stageRule = selectedStageId ? rules.stage_rules[selectedStageId] : null;
  const unsatisfiedChecks = stageQuantityChecks?.filter((c) => !c.satisfied) ?? [];

  const unverified = network.stages.filter((s) => network.unverified_stage_ids.includes(s.stage_id));
  const shifting = network.stages.filter((s) => s.shifts_project_finish);

  // Таблица факторов риска: комбинация уже доступных источников (без нового backend-поля):
  // конкретные факторы текущего этапа (`/forecast`), остальные этапы, сдвигающие срок
  // сдачи, и непокрытые ими периоды погодного риска (`/weather-risks`). Каждый этап попадает
  // в таблицу только один раз, чтобы не дублировать очевидные вещи.
  interface RiskRow {
    key: string;
    factor: string;
    message: string;
    severityLabel: string;
    accent: "danger" | "warning" | "ok";
  }
  const riskRows: RiskRow[] = [];
  const coveredStageIds = new Set<string>();
  if (stageForecast?.available && stageForecast.risk_factors) {
    for (const f of stageForecast.risk_factors) {
      riskRows.push({
        key: `forecast-${f.key}`,
        factor: RISK_KEY_LABEL[f.key] ?? (stageForecast.work_name ?? "Текущий этап"),
        message: f.message,
        severityLabel: SEVERITY_LABEL[f.severity],
        accent: SEVERITY_ACCENT[f.severity],
      });
    }
    if (stageForecast.stage_id) coveredStageIds.add(stageForecast.stage_id);
  }
  for (const stage of shifting) {
    if (coveredStageIds.has(stage.stage_id)) continue;
    riskRows.push({
      key: `stage-${stage.stage_id}`,
      factor: "Отставание по графику",
      message: `${stage.work_name}: ${stage.reason || "срок сдачи отодвинут."}`,
      severityLabel: stage.is_critical ? "Высокое" : "Среднее",
      accent: stage.is_critical ? "danger" : "warning",
    });
    coveredStageIds.add(stage.stage_id);
  }
  for (const period of weatherRisks?.risk_periods ?? []) {
    if (coveredStageIds.has(period.stage_id)) continue;
    riskRows.push({
      key: `weather-${period.stage_id}-${period.start_time_utc}`,
      factor: "Погода",
      message: `${period.work_name}: ${period.message}`,
      severityLabel: "Среднее",
      accent: "warning",
    });
  }

  const leafStages = network.stages.filter((s) => !s.is_summary);
  const doneCount = leafStages.filter((s) => s.state === "done_on_time" || s.state === "started_early").length;
  const inProgressCount = leafStages.filter((s) => s.state === "in_progress").length;
  const attentionCount = leafStages.filter((s) => s.state === "overdue" || s.state === "unverified").length;
  const stageKpis = [leafStages.length, doneCount, inProgressCount, attentionCount];

  const upcoming = [...leafStages]
    .filter((s) => new Date(s.planned_end_date) >= today && s.state !== "done_on_time")
    .sort((a, b) => new Date(a.planned_end_date).getTime() - new Date(b.planned_end_date).getTime())
    .slice(0, 5);

  const topGroups = network.stages.filter((s) => s.is_summary && !s.parent_id);
  // Обобщённая версия: работает для любого раздела (не только верхнего уровня) — нужна
  // для мини-прогресса у каждой строки-группы на диаграмме, а не только в сводке снизу.
  const groupCompliance = (group: NetworkStage): number | null => {
    const idsInGroup = new Set<string>();
    const collect = (id: string) => {
      idsInGroup.add(id);
      for (const s of network.stages) if (s.parent_id === id) collect(s.stage_id);
    };
    collect(group.stage_id);
    const values = network.stages
      .filter((s) => !s.is_summary && idsInGroup.has(s.stage_id) && s.compliance_percent !== null)
      .map((s) => s.compliance_percent as number);
    if (values.length === 0) return null;
    return Math.round(values.reduce((a, b) => a + b, 0) / values.length);
  };

  const selectedZoneEvents = selectedStage
    ? (events ?? []).filter((e) => e.zone_name === zoneName(selectedStage.zone_id)).slice(0, 3)
    : [];

  const renderTaskRow = (stage: NetworkStage) => {
    const color = stateColor(stage.state);
    const floatLabel = stage.is_critical
      ? "критический путь"
      : `запас ${stage.total_float_days} ${plural(stage.total_float_days)}`;
    const number = stageNumbers.get(stage.stage_id);
    const groupPercent = stage.is_summary ? groupCompliance(stage) : null;

    return (
      <button
        key={stage.stage_id}
        type="button"
        className={[
          "sk-network-row",
          stage.stage_id === selectedStageId ? "sk-network-row--selected" : "",
          stage.is_summary ? "sk-network-row--summary" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        title={`${floatLabel} · ${stage.state_label_ru || "—"}`}
        onClick={() => setSelectedStageId(stage.stage_id)}
      >
        <span className="sk-network-row__name" style={{ paddingLeft: `${stage.level * 16}px` }}>
          {stage.is_critical && (
            <span className="sk-network-row__critical" title="Критический путь">
              ▲
            </span>
          )}
          {number && (
            <span className={stage.is_summary ? "sk-network-row__number" : "sk-network-row__number sk-network-row__number--leaf"}>
              {number}
            </span>
          )}
          {!stage.is_summary && <i className="sk-network-row__bullet" style={{ background: color }} />}
          <span className="sk-network-row__text">{stage.work_name}</span>
        </span>
        {stage.is_summary ? (
          <span className="sk-network-row__group-progress">
            <span className="sk-network-row__mini-progress">
              <i style={{ width: `${groupPercent ?? 0}%`, background: groupPercent === null ? "var(--sk-text-faint)" : color }} />
            </span>
            {groupPercent !== null ? `${groupPercent}%` : "—"}
          </span>
        ) : (
          <span className="sk-network-row__percent">
            {stage.compliance_percent !== null ? `${stage.compliance_percent}%` : "—"}
          </span>
        )}
      </button>
    );
  };

  return (
    <div className="sk-schedule-page">
      <div className="sk-schedule-header">
        <div>
          <h1>Календарный план</h1>
          {network.schedule_is_demo && (
            <p className="sk-demo-note">
              Демонстрационный график: даты, иерархия работ и связи предшествования заданы для прототипа, в
              исходных материалах календаря нет.
            </p>
          )}
        </div>
        <div className="sk-schedule-header__tools">
          <div className="sk-schedule-tabs" role="group" aria-label="Вид">
            <button
              type="button"
              className={`sk-schedule-tabs__btn${view === "gantt" ? " sk-schedule-tabs__btn--active" : ""}`}
              onClick={() => setView("gantt")}
            >
              Гант
            </button>
            <button
              type="button"
              className={`sk-schedule-tabs__btn${view === "list" ? " sk-schedule-tabs__btn--active" : ""}`}
              onClick={() => setView("list")}
            >
              Список
            </button>
          </div>
          {isAdmin && (
            <>
              <button
                type="button"
                className="sk-button sk-button--secondary"
                onClick={() => {
                  setScheduleEditMode((v) => !v);
                  setCreatingStage(false);
                  setStageFormError(null);
                  setDetailTab("overview");
                }}
              >
                {scheduleEditMode ? "Завершить редактирование" : "Редактировать план"}
              </button>
              {scheduleEditMode && (
                <button type="button" className="sk-button" onClick={startCreateStage}>
                  + Новый этап
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {!network.available ? (
        <div className="sk-panel sk-panel--error" style={{ marginTop: "var(--sk-space-5)" }}>
          <p>{network.reason}</p>
          {network.cycle.length > 0 && (
            <p className="sk-table__muted">
              Работы в цикле: {network.cycle.join(", ")}. Уберите лишнюю связь предшествования в
              админке, чтобы расчёт стал возможен.
            </p>
          )}
        </div>
      ) : (
        <>
          <div className="sk-delivery">
            <div className={`sk-delivery__verdict sk-delivery__verdict--${network.status}`}>
              <span className="sk-delivery__label">Срок сдачи объекта</span>
              <strong>{network.status_label_ru}</strong>
              {network.shift_days !== 0 && (
                <span className="sk-delivery__shift">
                  {network.shift_days > 0 ? "+" : "−"}
                  {Math.abs(network.shift_days)} {plural(network.shift_days)}
                </span>
              )}
            </div>
            <div className="sk-delivery__dates">
              <div>
                <span className="sk-delivery__label">По графику</span>
                <strong>{network.baseline_finish_date ? formatDate(network.baseline_finish_date) : "—"}</strong>
              </div>
              <div>
                <span className="sk-delivery__label">Прогноз по фотоконтролю</span>
                <strong>
                  {network.projected_finish_date ? formatDate(network.projected_finish_date) : "—"}
                </strong>
              </div>
            </div>
          </div>

          {view === "gantt" ? (
            <div className="sk-schedule-workspace">
              <div className="sk-schedule-left">
                <section className="sk-panel sk-gantt-card">
                  <div className="sk-gantt-header-row">
                    <div className="sk-gantt-task-header">
                      <span>Этап / Задача</span>
                      <span className="sk-gantt-task-header__percent">Факт</span>
                    </div>
                    <div className="sk-gantt-month-head">
                      <div className="sk-gantt-months">
                        {months.map((m, i) => (
                          <div key={i} style={{ flexGrow: m.days, flexBasis: 0 }}>
                            {m.label}
                          </div>
                        ))}
                      </div>
                      <div className="sk-gantt-days">
                        {dayTicks.map((t, i) => (
                          <span key={i} style={{ left: `${t.left}%` }}>
                            {t.label}
                          </span>
                        ))}
                      </div>
                      {todayPosition >= 0 && todayPosition <= 100 && (
                        <span className="sk-gantt-today-label" style={{ left: `${todayPosition}%` }}>
                          Сегодня
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="sk-gantt-grid">
                    <div className="sk-gantt-task-side">
                      <div className="sk-network">{network.stages.map(renderTaskRow)}</div>
                    </div>
                    <div className="sk-gantt-timeline-wrap">
                      <div className="sk-gantt-timeline">
                        {todayPosition >= 0 && todayPosition <= 100 && (
                          <span className="sk-gantt-today-line" style={{ left: `${todayPosition}%` }} />
                        )}
                        <div className="sk-gantt-timeline-rows">
                          {network.stages.map((stage) => {
                            const planned = barPosition(stage.planned_start_date, stage.planned_end_date);
                            const overrun =
                              stage.projected_finish_date > stage.planned_end_date
                                ? barPosition(stage.planned_end_date, stage.projected_finish_date)
                                : null;
                            const color = stateColor(stage.state);
                            return (
                              <div
                                key={stage.stage_id}
                                className={`sk-gantt-timeline-row${stage.is_summary ? " sk-gantt-timeline-row--summary" : ""}`}
                              >
                                <span
                                  className="sk-gantt-bar"
                                  style={{
                                    left: `${planned.left}%`,
                                    width: `${planned.width}%`,
                                    background: stage.is_summary ? "transparent" : color,
                                    borderColor: stage.is_summary ? "var(--sk-border-strong)" : "transparent",
                                  }}
                                />
                                {overrun && (
                                  <span
                                    className="sk-gantt-bar sk-gantt-bar--overrun"
                                    style={{ left: `${overrun.left}%`, width: `${overrun.width}%` }}
                                    title={`Прогноз окончания ${formatDate(stage.projected_finish_date)}`}
                                  />
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="sk-gantt-legend">
                    <span className="sk-gantt-legend__item">
                      <i className="sk-gantt-legend__dot" style={{ background: "var(--sk-status-ok)" }} />
                      Выполнено / досрочно
                    </span>
                    <span className="sk-gantt-legend__item">
                      <i className="sk-gantt-legend__dot" style={{ background: "var(--sk-accent)" }} />
                      В работе
                    </span>
                    <span className="sk-gantt-legend__item">
                      <i className="sk-gantt-legend__dot" style={{ background: "var(--sk-text-faint)" }} />
                      Не начато
                    </span>
                    <span className="sk-gantt-legend__item">
                      <i className="sk-gantt-legend__dot" style={{ background: "var(--sk-status-danger)" }} />
                      Просрочено
                    </span>
                    <span className="sk-gantt-legend__item">
                      <i className="sk-gantt-legend__dot" style={{ background: "var(--sk-status-warning)" }} />
                      Не подтверждено
                    </span>
                    <span className="sk-gantt-legend__item">
                      <i className="sk-gantt-legend__stripe" />
                      Прогнозный перерасход
                    </span>
                    <span className="sk-gantt-legend__item">▲ критический путь</span>
                  </div>
                </section>

                <section className="sk-panel sk-schedule-summary">
                  <div className="sk-schedule-summary__section">
                    <div className="sk-schedule-summary__title">Ключевые этапы</div>
                    <div className="sk-schedule-kpis">
                      {STAGE_KPI_LABELS.map((label, i) => (
                        <div key={label} className="sk-schedule-kpi">
                          <div className="sk-schedule-kpi__label">{label}</div>
                          <div className="sk-schedule-kpi__number">{stageKpis[i]}</div>
                          {leafStages.length > 0 && i > 0 && (
                            <div className="sk-schedule-kpi__foot">
                              {Math.round((stageKpis[i] / leafStages.length) * 100)}%
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="sk-schedule-summary__section">
                    <div className="sk-schedule-summary__title">Ближайшие события</div>
                    {upcoming.length === 0 ? (
                      <p className="sk-empty-state">Нет предстоящих сроков.</p>
                    ) : (
                      <div className="sk-schedule-upcoming">
                        {upcoming.map((s) => (
                          <div key={s.stage_id} className="sk-schedule-upcoming__row">
                            <span className="sk-schedule-upcoming__date">{formatShortDate(s.planned_end_date)}</span>
                            <span className="sk-schedule-upcoming__name">{s.work_name}</span>
                            <span
                              className={`sk-pill${
                                s.state === "overdue" || s.state === "unverified" ? " sk-pill--red" : " sk-pill--green"
                              }`}
                            >
                              {s.state === "overdue" || s.state === "unverified" ? `+${s.delay_days} дн` : "В срок"}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="sk-schedule-summary__section">
                    <div className="sk-schedule-summary__title">Прогресс по этапам (факт)</div>
                    {topGroups.length === 0 ? (
                      <p className="sk-empty-state">Разделы графика не заданы.</p>
                    ) : (
                      <div className="sk-schedule-stage-progress">
                        {topGroups.map((g) => {
                          const percent = groupCompliance(g);
                          return (
                            <div key={g.stage_id} className="sk-schedule-stage-line">
                              <span title={g.work_name}>{g.work_name}</span>
                              <div className="sk-schedule-stage-line__track">
                                <div
                                  className="sk-schedule-stage-line__fill"
                                  style={{
                                    width: `${percent ?? 0}%`,
                                    background: percent === null ? "var(--sk-text-faint)" : undefined,
                                  }}
                                />
                              </div>
                              <b>{percent !== null ? `${percent}%` : "—"}</b>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </section>

                <WeatherRiskPanel />
              </div>

              <aside className="sk-panel sk-stage-detail">
                {creatingStage ? (
                  <>
                    <div className="sk-stage-detail__head">
                      <h2>Новый этап</h2>
                    </div>
                    <StageEditForm
                      mode="create"
                      initial={null}
                      defaultZoneId={zonesForEdit?.[0]?.zone_id ?? ""}
                      zones={zonesForEdit ?? []}
                      otherStages={stagesDetail ?? []}
                      vocabulary={vocabulary ?? []}
                      busy={savingStage}
                      error={stageFormError}
                      onSubmit={(payload) => void submitCreateStage(payload)}
                      onCancel={cancelStageForm}
                    />
                  </>
                ) : selectedStage ? (
                  <>
                    <div className="sk-stage-detail__head">
                      <div>
                        <h2>{selectedStage.work_name}</h2>
                        <div className="sk-stage-detail__sub">Зона {zoneName(selectedStage.zone_id)}</div>
                      </div>
                      <span
                        className="sk-stage-detail__badge"
                        style={{ color: stateColor(selectedStage.state), borderColor: stateColor(selectedStage.state) }}
                      >
                        {selectedStage.state_label_ru || "—"}
                      </span>
                    </div>

                    <div className="sk-stage-detail__tabs">
                      <button
                        type="button"
                        className={detailTab === "overview" ? "sk-stage-detail__tab--active" : ""}
                        onClick={() => setDetailTab("overview")}
                      >
                        Обзор
                      </button>
                      <button
                        type="button"
                        className={detailTab === "equipment" ? "sk-stage-detail__tab--active" : ""}
                        onClick={() => setDetailTab("equipment")}
                      >
                        Техника
                      </button>
                      {scheduleEditMode && isAdmin && (
                        <button
                          type="button"
                          className={detailTab === "edit" ? "sk-stage-detail__tab--active" : ""}
                          onClick={() => setDetailTab("edit")}
                        >
                          Редактировать
                        </button>
                      )}
                    </div>

                    {detailTab === "overview" ? (
                      <>
                        {!selectedStage.is_summary && (
                          <div className="sk-stage-detail__block">
                            <div className="sk-stage-detail__block-title">Прогресс этапа</div>
                            <div className="sk-progress-flex">
                              <div
                                className="sk-progress-ring"
                                style={{
                                  background: `conic-gradient(var(--sk-status-ok) 0 ${selectedStage.compliance_percent ?? 0}%, var(--sk-surface-muted) ${selectedStage.compliance_percent ?? 0}% 100%)`,
                                }}
                              >
                                <span>{selectedStage.compliance_percent !== null ? `${selectedStage.compliance_percent}%` : "—"}</span>
                              </div>
                              <div className="sk-plan-fact">
                                <div>
                                  <small>План (время)</small>
                                  <strong>{timeProgressPercent(selectedStage, today)}%</strong>
                                </div>
                                <div>
                                  <small>Факт (без отклонений)</small>
                                  <strong>{selectedStage.compliance_percent !== null ? `${selectedStage.compliance_percent}%` : "—"}</strong>
                                </div>
                              </div>
                            </div>
                          </div>
                        )}

                        <div className="sk-stage-detail__block">
                          <div className="sk-stage-detail__block-title">Сроки</div>
                          <div className="sk-date-list">
                            <div className="sk-date-row">
                              <span>▦</span>
                              <div>
                                <small>План</small>
                                {formatDate(selectedStage.planned_start_date)} – {formatDate(selectedStage.planned_end_date)}
                              </div>
                            </div>
                            <div className="sk-date-row">
                              <span>▦</span>
                              <div>
                                <small>Прогноз</small>
                                {formatDate(selectedStage.projected_finish_date)}
                              </div>
                              {selectedStage.delay_days > 0 && (
                                <strong className="sk-date-row__delay">+{selectedStage.delay_days} дн.</strong>
                              )}
                            </div>
                          </div>
                          <p className="sk-table__muted" style={{ marginTop: "var(--sk-space-2)" }}>
                            Ранний старт {formatDate(selectedStage.early_start_date)}, поздний старт{" "}
                            {formatDate(selectedStage.late_start_date)} — запас {selectedStage.total_float_days}{" "}
                            {plural(selectedStage.total_float_days)}.
                          </p>
                        </div>

                        {(selectedStage.state === "overdue" || selectedStage.state === "unverified" || unsatisfiedChecks.length > 0) && (
                          <div className="sk-stage-alert">
                            <div className="sk-stage-alert__icon">!</div>
                            <div>
                              <strong>Отклонение</strong>
                              {selectedStage.reason && <p>{selectedStage.reason}</p>}
                              {unsatisfiedChecks.map((c) => (
                                <p key={c.class_key}>
                                  Недостаточно техники: {c.label_ru} (факт {c.actual_qty} из {c.required_qty})
                                </p>
                              ))}
                            </div>
                          </div>
                        )}

                        {selectedZoneEvents.length > 0 && (
                          <div className="sk-stage-detail__block sk-stage-detail__block--last">
                            <div className="sk-stage-detail__block-title">Последние события зоны</div>
                            <div className="sk-last-events">
                              {selectedZoneEvents.map((e) => (
                                <div key={e.id} className="sk-last-event">
                                  <i className="sk-last-event__dot" />
                                  <span className="sk-last-event__time">
                                    {new Date(e.created_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}
                                  </span>
                                  <span>
                                    {e.title}
                                    <small>{e.kind_label_ru}</small>
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    ) : detailTab === "edit" ? (
                      <StageEditForm
                        mode="edit"
                        stageId={selectedStage.stage_id}
                        initial={stagesDetail?.find((s) => s.stage_id === selectedStage.stage_id) ?? null}
                        defaultZoneId={selectedStage.zone_id}
                        zones={zonesForEdit ?? []}
                        otherStages={stagesDetail ?? []}
                        vocabulary={vocabulary ?? []}
                        busy={savingStage}
                        error={stageFormError}
                        onSubmit={(payload) => void submitEditStage(selectedStage.stage_id, payload)}
                        onCancel={() => {
                          setStageFormError(null);
                          setDetailTab("overview");
                        }}
                        onDelete={() => void confirmDeleteStage(selectedStage.stage_id)}
                      />
                    ) : selectedStage.is_summary ? (
                      <p className="sk-empty-state">
                        Это укрупнённая работа: своей технологии у неё нет, состав техники проверяется по
                        вложенным работам.
                      </p>
                    ) : stageRule ? (
                      <div className="sk-stage-detail__block">
                        {selectedObservation ? (
                          <p className="sk-table__muted">
                            По последнему наблюдению зоны ({new Date(selectedObservation.created_at).toLocaleString("ru-RU")}
                            ) —{" "}
                            <StatusBadge
                              status={selectedObservation.overall_status}
                              label={selectedObservation.overall_status_label_ru}
                            />
                          </p>
                        ) : (
                          <p className="sk-empty-state">Для этой зоны ещё нет проанализированных снимков.</p>
                        )}
                        <div className="sk-equipment-list">
                          {Object.entries(stageRule.required_quantities).map(([classKey, requiredQty]) => {
                            const check = stageQuantityChecks?.find((c) => c.class_key === classKey);
                            const satisfied = check ? check.satisfied : false;
                            return (
                              <div key={classKey} className="sk-equipment-row">
                                <EquipmentIcon
                                  classKey={classKey}
                                  className="sk-equipment-row__icon"
                                  style={{ color: satisfied ? "var(--sk-status-ok)" : "var(--sk-status-warning)" }}
                                />
                                <span>{check?.label_ru ?? classKey}</span>
                                <span className="sk-equipment-row__count">
                                  {check ? check.actual_qty : selectedObservation ? 0 : "—"} / {requiredQty}
                                </span>
                                <span
                                  className={`sk-equipment-row__status${satisfied ? "" : " sk-equipment-row__status--warn"}`}
                                >
                                  {check ? (satisfied ? "✓" : "!") : "?"}
                                </span>
                              </div>
                            );
                          })}
                          {Object.keys(stageRule.required_quantities).length === 0 && (
                            <p className="sk-table__muted">
                              Для этого этапа не заданы количественные требования — проверяется только наличие класса.
                            </p>
                          )}
                        </div>
                        <p className="sk-table__muted" style={{ marginTop: "var(--sk-space-3)" }}>
                          Допустимо сверх плана: {stageRule.allowed.join(", ") || "—"}
                        </p>
                        {stageRule.alternatives_note && <p className="sk-table__muted">{stageRule.alternatives_note}</p>}
                      </div>
                    ) : (
                      <p className="sk-empty-state">Для этой работы не задано правило техники.</p>
                    )}
                  </>
                ) : (
                  <p className="sk-empty-state">Выберите работу на диаграмме слева.</p>
                )}
              </aside>
            </div>
          ) : (
            <div className="sk-panel" style={{ marginTop: "var(--sk-space-5)" }}>
              <table className="sk-table">
                <thead>
                  <tr>
                    <th>Работа</th>
                    <th>Зона</th>
                    <th>План</th>
                    <th>Прогноз</th>
                    <th>Факт</th>
                    <th>Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {network.stages.map((stage) => (
                    <tr
                      key={stage.stage_id}
                      className={stage.stage_id === selectedStageId ? "sk-table__row--selected" : undefined}
                      onClick={() => setSelectedStageId(stage.stage_id)}
                      style={{ cursor: "pointer", fontWeight: stage.is_summary ? 600 : undefined }}
                    >
                      <td style={{ paddingLeft: `${12 + stage.level * 16}px` }}>
                        {stage.is_critical && <span className="sk-network-row__critical">▲ </span>}
                        {stage.work_name}
                      </td>
                      <td>{zoneName(stage.zone_id)}</td>
                      <td>
                        {formatShortDate(stage.planned_start_date)} – {formatShortDate(stage.planned_end_date)}
                      </td>
                      <td className={stage.delay_days > 0 ? "sk-quantity-mismatch" : undefined}>
                        {formatShortDate(stage.projected_finish_date)}
                      </td>
                      <td>{stage.compliance_percent !== null ? `${stage.compliance_percent}%` : "—"}</td>
                      <td>{stage.state_label_ru || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <section className="sk-panel sk-schedule-dynamics">
            <h2>Динамика проекта</h2>
            {dynamics ? (
              <ProjectDynamicsChart
                plan={dynamics.plan}
                fact={dynamics.fact}
                forecast={dynamics.forecast}
                today={dynamics.today}
              />
            ) : (
              <p className="sk-empty-state">Недостаточно данных графика, чтобы построить динамику.</p>
            )}
          </section>

          {network.delay_breakdown.available && (
            <div className="sk-schedule-risk-row">
              <section className="sk-panel sk-schedule-risk-donut">
                <h2>Влияние факторов на прогноз</h2>
                <DelayFactorsDonut breakdown={network.delay_breakdown} />
                {network.delay_breakdown.method_note && (
                  <p className="sk-table__muted" style={{ marginTop: "var(--sk-space-3)" }}>
                    {network.delay_breakdown.method_note}
                  </p>
                )}
              </section>

              <section className="sk-panel sk-schedule-risk-table">
                <h2>Таблица факторов риска</h2>
                {riskRows.length === 0 ? (
                  <p className="sk-empty-state">Значимых факторов риска не выявлено.</p>
                ) : (
                  <table className="sk-table">
                    <thead>
                      <tr>
                        <th>Фактор</th>
                        <th>Описание</th>
                        <th>Влияние</th>
                      </tr>
                    </thead>
                    <tbody>
                      {riskRows.map((row) => (
                        <tr key={row.key}>
                          <td>{row.factor}</td>
                          <td>{row.message}</td>
                          <td>
                            <span className={`sk-risk-badge sk-risk-badge--${row.accent}`}>{row.severityLabel}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
            </div>
          )}

          {shifting.length > 0 && (
            <div className="sk-panel sk-schedule-alert">
              <h2>Что двигает дату сдачи</h2>
              <ul>
                {shifting.map((stage) => (
                  <li key={stage.stage_id}>
                    <strong>{stage.work_name}</strong>: отставание {stage.delay_days} {plural(stage.delay_days)} при
                    запасе {stage.total_float_days} {plural(stage.total_float_days)}. {stage.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {unverified.length > 0 && (
            <div className="sk-panel sk-schedule-unverified">
              <h2>Вне контроля по снимкам</h2>
              <p className="sk-table__muted">
                У этих работ плановый срок истёк, но ни одного снимка с подтверждённой датой за период нет. Это не
                значит, что работы выполнены — их ход камерами не проверен.
              </p>
              <ul>
                {unverified.map((stage) => (
                  <li key={stage.stage_id}>
                    {stage.work_name} (до {formatDate(stage.planned_end_date)})
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
