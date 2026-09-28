import { useEffect, useMemo, useState } from "react";
import {
  createStage,
  deleteStage,
  fetchDashboard,
  fetchObservation,
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

const SEVERITY_LABEL: Record<RiskFactor["severity"], string> = { high: "Высокое", medium: "Среднее", low: "Низкое" };
const SEVERITY_ACCENT: Record<RiskFactor["severity"], "danger" | "warning" | "ok"> = {
  high: "danger",
  medium: "warning",
  low: "ok",
};

function dayDiff(a: Date, b: Date): number {
  return Math.round((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24));
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function plural(days: number): string {
  const n = Math.abs(days) % 100;
  const last = n % 10;
  if (n > 10 && n < 20) return "дней";
  if (last === 1) return "день";
  if (last >= 2 && last <= 4) return "дня";
  return "дней";
}

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

export function SchedulePage() {
  const { projectId } = useProject();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [rules, setRules] = useState<RulesResponse | null>(null);
  const [network, setNetwork] = useState<ScheduleNetworkResponse | null>(null);
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [stageForecast, setStageForecast] = useState<ForecastResponse | null>(null);
  const [weatherRisks, setWeatherRisks] = useState<WeatherRiskResponse | null>(null);
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);
  const [selectedObservation, setSelectedObservation] = useState<ObservationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<"overview" | "equipment" | "edit">("overview");

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
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
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
      .then((data) => !cancelled && setSelectedObservation(data))
      .catch(() => !cancelled && setSelectedObservation(null));
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
    setSelectedStageId(null);
    setCreatingStage(true);
    setStageFormError(null);
  };

  const cancelStageForm = () => {
    setCreatingStage(false);
    setStageFormError(null);
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

  const dynamics = useMemo(() => {
    if (!network || !network.available) return null;
    const leaf = network.stages.filter((s) => !s.is_summary);
    if (leaf.length === 0) return null;
    const sorted = [...leaf].sort((a, b) => new Date(a.planned_start_date).getTime() - new Date(b.planned_start_date).getTime());
    const totalDuration = sorted.reduce((sum, s) => sum + dayDiff(new Date(s.planned_start_date), new Date(s.planned_end_date)) + 1, 0);

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
    const forecastStart: DynamicsPoint = fact.length > 0 ? fact[fact.length - 1] : { date: todayIso, percent: interpolate(plan, todayIso) };
    const forecast: DynamicsPoint[] = [];
    if (network.projected_finish_date && new Date(network.projected_finish_date).getTime() > new Date(forecastStart.date).getTime()) {
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
  const zoneName = (zoneId: string) => dashboard.zones.find((z) => z.zone_id === zoneId)?.name ?? zoneId;
  const stageQuantityChecks = selectedObservation?.stages.find((s) => s.stage_id === selectedStageId)?.quantity_checks;
  const stageRule = selectedStageId ? rules.stage_rules[selectedStageId] : null;
  const unsatisfiedChecks = stageQuantityChecks?.filter((c) => !c.satisfied) ?? [];
  const unverified = network.stages.filter((s) => network.unverified_stage_ids.includes(s.stage_id));
  const shifting = network.stages.filter((s) => s.shifts_project_finish);

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

  return (
    <div className="sk-schedule-page">
      <div className="sk-schedule-header">
        <h1>Календарный план</h1>
        {isAdmin && (
          <div className="sk-schedule-header__tools">
            <button
              type="button"
              className="sk-button sk-button--secondary"
              onClick={() => {
                setScheduleEditMode((v) => !v);
                setCreatingStage(false);
                setStageFormError(null);
              }}
            >
              {scheduleEditMode ? "Завершить редактирование" : "Редактировать"}
            </button>
            {scheduleEditMode && (
              <button type="button" className="sk-button" onClick={startCreateStage}>
                + Новый этап
              </button>
            )}
          </div>
        )}
      </div>

      {network.schedule_is_demo && <p className="sk-demo-note">Координаты и график — демонстрационные данные.</p>}

      {!network.available ? (
        <div className="sk-panel sk-panel--error" style={{ marginTop: "var(--sk-space-4)" }}>
          <p>{network.reason}</p>
          {network.cycle.length > 0 && <p className="sk-table__muted">Работы в цикле: {network.cycle.join(", ")}.</p>}
        </div>
      ) : (
        <>
          <div className={`sk-panel sk-delivery sk-delivery--${network.status}`}>
            <span className="sk-delivery__label">Срок сдачи объекта</span>
            <strong>{network.status_label_ru}</strong>
            {network.shift_days !== 0 && (
              <span className="sk-delivery__shift">
                {network.shift_days > 0 ? "+" : "−"}
                {Math.abs(network.shift_days)} {plural(network.shift_days)}
              </span>
            )}
            <div className="sk-delivery__dates">
              <div>
                <span className="sk-delivery__label">По графику</span>
                <strong>{network.baseline_finish_date ? formatDate(network.baseline_finish_date) : "—"}</strong>
              </div>
              <div>
                <span className="sk-delivery__label">Прогноз</span>
                <strong>{network.projected_finish_date ? formatDate(network.projected_finish_date) : "—"}</strong>
              </div>
            </div>
          </div>

          {creatingStage && (
            <div className="sk-panel sk-stage-detail" style={{ marginTop: "var(--sk-space-4)" }}>
              <h2>Новый этап</h2>
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
            </div>
          )}

          <div className="sk-stage-list">
            {network.stages.map((stage) => {
              const expanded = stage.stage_id === selectedStageId;
              return (
                <div key={stage.stage_id} className="sk-panel sk-stage-row-card">
                  <button
                    type="button"
                    className="sk-stage-row-card__head"
                    onClick={() => setSelectedStageId(expanded ? null : stage.stage_id)}
                  >
                    <span className="sk-stage-row-card__number">{stageNumbers.get(stage.stage_id)}</span>
                    <span className="sk-stage-row-card__main">
                      <span className="sk-stage-row-card__name">
                        {stage.is_critical && <i className="sk-stage-row-card__critical" title="Критический путь">▲</i>}
                        {stage.work_name}
                      </span>
                      <span className="sk-stage-row-card__meta">
                        {zoneName(stage.zone_id)} · {formatDate(stage.planned_start_date)}–{formatDate(stage.planned_end_date)}
                      </span>
                      <div className="sk-progress-bar" style={{ marginTop: 4 }}>
                        <div
                          className="sk-progress-bar__fill"
                          style={{ width: `${stage.compliance_percent ?? 0}%`, background: stateColor(stage.state) }}
                        />
                      </div>
                    </span>
                    <span className="sk-stage-row-card__chevron">{expanded ? "︿" : "﹀"}</span>
                  </button>

                  {expanded && (
                    <div className="sk-stage-detail">
                      <div className="sk-stage-detail__head">
                        <span
                          className="sk-stage-detail__badge"
                          style={{ color: stateColor(stage.state), borderColor: stateColor(stage.state) }}
                        >
                          {stage.state_label_ru || "—"}
                        </span>
                      </div>

                      <div className="sk-stage-detail__tabs">
                        <button type="button" className={detailTab === "overview" ? "sk-stage-detail__tab--active" : ""} onClick={() => setDetailTab("overview")}>
                          Обзор
                        </button>
                        <button type="button" className={detailTab === "equipment" ? "sk-stage-detail__tab--active" : ""} onClick={() => setDetailTab("equipment")}>
                          Техника
                        </button>
                        {scheduleEditMode && isAdmin && (
                          <button type="button" className={detailTab === "edit" ? "sk-stage-detail__tab--active" : ""} onClick={() => setDetailTab("edit")}>
                            Редактировать
                          </button>
                        )}
                      </div>

                      {detailTab === "overview" ? (
                        <>
                          {!stage.is_summary && (
                            <div className="sk-stage-detail__block">
                              <div className="sk-progress-flex">
                                <div
                                  className="sk-progress-ring"
                                  style={{
                                    background: `conic-gradient(var(--sk-status-ok) 0 ${stage.compliance_percent ?? 0}%, var(--sk-surface-muted) ${stage.compliance_percent ?? 0}% 100%)`,
                                  }}
                                >
                                  <span>{stage.compliance_percent !== null ? `${stage.compliance_percent}%` : "—"}</span>
                                </div>
                                <div className="sk-plan-fact">
                                  <div>
                                    <small>План (время)</small>
                                    <strong>{timeProgressPercent(stage, today)}%</strong>
                                  </div>
                                  <div>
                                    <small>Факт (без отклонений)</small>
                                    <strong>{stage.compliance_percent !== null ? `${stage.compliance_percent}%` : "—"}</strong>
                                  </div>
                                </div>
                              </div>
                            </div>
                          )}

                          <div className="sk-stage-detail__block">
                            <p className="sk-table__muted">
                              Прогноз: {formatDate(stage.projected_finish_date)}
                              {stage.delay_days > 0 && <strong className="sk-quantity-mismatch"> +{stage.delay_days} дн.</strong>}
                            </p>
                            <p className="sk-table__muted">
                              Запас времени: {stage.total_float_days} {plural(stage.total_float_days)}
                            </p>
                          </div>

                          {(stage.state === "overdue" || stage.state === "unverified" || unsatisfiedChecks.length > 0) && (
                            <div className="sk-stage-alert">
                              <strong>Отклонение</strong>
                              {stage.reason && <p>{stage.reason}</p>}
                              {unsatisfiedChecks.map((c) => (
                                <p key={c.class_key}>
                                  Недостаточно техники: {c.label_ru} (факт {c.actual_qty} из {c.required_qty})
                                </p>
                              ))}
                            </div>
                          )}
                        </>
                      ) : detailTab === "edit" ? (
                        <StageEditForm
                          mode="edit"
                          stageId={stage.stage_id}
                          initial={stagesDetail?.find((s) => s.stage_id === stage.stage_id) ?? null}
                          defaultZoneId={stage.zone_id}
                          zones={zonesForEdit ?? []}
                          otherStages={stagesDetail ?? []}
                          vocabulary={vocabulary ?? []}
                          busy={savingStage}
                          error={stageFormError}
                          onSubmit={(payload) => void submitEditStage(stage.stage_id, payload)}
                          onCancel={() => {
                            setStageFormError(null);
                            setDetailTab("overview");
                          }}
                          onDelete={() => void confirmDeleteStage(stage.stage_id)}
                        />
                      ) : stage.is_summary ? (
                        <p className="sk-empty-state">Укрупнённая работа — своей технологии нет.</p>
                      ) : stageRule ? (
                        <div className="sk-stage-detail__block">
                          {selectedObservation ? (
                            <p className="sk-table__muted">
                              {new Date(selectedObservation.created_at).toLocaleString("ru-RU")} —{" "}
                              <StatusBadge status={selectedObservation.overall_status} label={selectedObservation.overall_status_label_ru} />
                            </p>
                          ) : (
                            <p className="sk-empty-state">Для этой зоны ещё нет проанализированных снимков.</p>
                          )}
                          <p className="sk-table__muted" style={{ marginTop: "var(--sk-space-2)" }}>
                            Допустимо сверх плана: {stageRule.allowed.join(", ") || "—"}
                          </p>
                        </div>
                      ) : (
                        <p className="sk-empty-state">Для этой работы не задано правило техники.</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <section className="sk-panel sk-schedule-dynamics">
            <h2>Динамика проекта</h2>
            {dynamics ? (
              <ProjectDynamicsChart plan={dynamics.plan} fact={dynamics.fact} forecast={dynamics.forecast} today={dynamics.today} />
            ) : (
              <p className="sk-empty-state">Недостаточно данных, чтобы построить динамику.</p>
            )}
          </section>

          {network.delay_breakdown.available && (
            <>
              <section className="sk-panel" style={{ marginTop: "var(--sk-space-4)" }}>
                <h2>Влияние факторов на прогноз</h2>
                <DelayFactorsDonut breakdown={network.delay_breakdown} />
              </section>

              <section className="sk-panel" style={{ marginTop: "var(--sk-space-4)" }}>
                <h2>Факторы риска</h2>
                {riskRows.length === 0 ? (
                  <p className="sk-empty-state">Значимых факторов риска не выявлено.</p>
                ) : (
                  <ul className="sk-risk-list">
                    {riskRows.map((row) => (
                      <li key={row.key} className="sk-risk-list__item">
                        <div className="sk-risk-list__top">
                          <strong>{row.factor}</strong>
                          <span className={`sk-risk-badge sk-risk-badge--${row.accent}`}>{row.severityLabel}</span>
                        </div>
                        <p>{row.message}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}

          <div style={{ marginTop: "var(--sk-space-4)" }}>
            <WeatherRiskPanel />
          </div>

          {shifting.length > 0 && (
            <div className="sk-panel sk-schedule-alert" style={{ marginTop: "var(--sk-space-4)" }}>
              <h2>Что двигает дату сдачи</h2>
              <ul>
                {shifting.map((stage) => (
                  <li key={stage.stage_id}>
                    <strong>{stage.work_name}</strong>: +{stage.delay_days} {plural(stage.delay_days)} при запасе {stage.total_float_days}.
                  </li>
                ))}
              </ul>
            </div>
          )}

          {unverified.length > 0 && (
            <div className="sk-panel sk-schedule-alert" style={{ marginTop: "var(--sk-space-4)" }}>
              <h2>Вне контроля по снимкам</h2>
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
