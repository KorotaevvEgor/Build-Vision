import {useEffect,useMemo,useState} from "react";
import {fetchDashboard,fetchObservation,fetchProjectEvents,fetchReadiness,fetchStages} from "../api";
import type {DashboardResponse,ForecastResponse,ObservationDetail,ProjectEventItem,ReadinessResponse,ScheduleNetworkResponse,StageDetail} from "../api";
import {useProject} from "../ProjectContext";
import {projectTimeZone} from "./projectTime";
import {ProjectDynamicsChart,type DynamicsPoint} from "./ProjectDynamicsChart";
import {DelayFactorsDonut} from "./DelayFactorsDonut";
import {WeatherRiskPanel} from "./WeatherRiskPanel";
import {StageEquipmentRequirements} from "./StageEquipmentRequirements";
import {DAY,dateStamp,durationDays,formatPlanDate} from "./scheduleV2Model";
import "./ForecastAnalysis.css";
import {projectPlanCurve} from "./projectPlanCurve";
const SEVERITY_LABEL={high:"Высокое",medium:"Среднее",low:"Низкое"};
const SEVERITY_ACCENT={high:"danger",medium:"warning",low:"ok"} as const;
const RISK_KEY_LABEL:Record<string,string>={missing_equipment:"Недостаток техники",pace_decline:"Ресурсное соответствие",resource_compliance_decline:"Ресурсное соответствие",weather:"Погода",deviation_history:"История отклонений",insufficient_data:"Данные"};
export function ForecastAnalysis({network,forecast,factorsLoading=false,factorsError="",forecastState="ready"}:{network:ScheduleNetworkResponse;forecast:ForecastResponse|null;factorsLoading?:boolean;factorsError?:string;forecastState?:"loading"|"ready"|"error"}){
 const {projectId,project}=useProject();const paused=project.status==="paused";const tz=projectTimeZone(project);
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
 const today=['year','month','day'].map(k=>parts.find(p=>p.type===k)?.value).join('-');
 const [dashboard,setDashboard]=useState<DashboardResponse|null>(null),[readiness,setReadiness]=useState<ReadinessResponse|null>(null),[events,setEvents]=useState<ProjectEventItem[]>([]),[details,setDetails]=useState<StageDetail[]>([]),[selectedId,setSelectedId]=useState(''),[tab,setTab]=useState('overview'),[observation,setObservation]=useState<ObservationDetail|null>(null);
 useEffect(()=>{let active=true;setDashboard(null);setReadiness(null);setEvents([]);setDetails([]);setSelectedId('');setObservation(null);Promise.allSettled([fetchDashboard(projectId),fetchReadiness(projectId),fetchProjectEvents(projectId,40),fetchStages(projectId)]).then(([d,r,e,s])=>{if(!active)return;if(d.status==='fulfilled')setDashboard(d.value);if(r.status==='fulfilled')setReadiness(r.value);if(e.status==='fulfilled')setEvents(e.value.items);if(s.status==='fulfilled')setDetails(s.value.stages);});return()=>{active=false;};},[projectId]);
 const selected=network.stages.find(s=>s.stage_id===selectedId)??network.stages.find(s=>!s.is_summary&&s.shifts_project_finish)??network.stages.find(s=>s.stage_id===dashboard?.current_stage?.stage_id)??network.stages.find(s=>!s.is_summary);
 const zone=dashboard?.zones.find(z=>z.zone_id===selected?.zone_id);const obsId=zone?.latest_observation?.observation_id;
 useEffect(()=>{let active=true;setObservation(null);if(obsId)fetchObservation(projectId,obsId).then(v=>active&&setObservation(v)).catch(()=>{});return()=>{active=false;};},[obsId,projectId]);
 const checks=observation?.stages.find(s=>s.stage_id===selected?.stage_id)?.quantity_checks??[];
 const shifting=paused?[]:network.stages.filter(s=>s.shifts_project_finish);
  const dynamics = useMemo(() => {
    if (!network || !network.available) return null;
    const leaf = network.stages.filter((s) => !s.is_summary);
    if (leaf.length === 0) return null;
    const plan: DynamicsPoint[] = projectPlanCurve(leaf);

    const fact: DynamicsPoint[] = (readiness?.fact ?? []).map((p) => ({ date: p.date, percent: p.readiness_percent }));

    const todayIso = today;
    const measured = leaf.filter(s=>s.physical_progress_percent != null && s.verified_progress_date);
    const forecast: DynamicsPoint[] = [];
    // Photo readiness cannot seed a physical completion scenario.
    if (!paused && measured.length === leaf.length && network.projected_finish_date) {
      const total = leaf.reduce((sum,s)=>sum+s.duration_days,0);
      const percent = measured.reduce((sum,s)=>sum+(s.physical_progress_percent??0)*s.duration_days,0)/Math.max(1,total);
      const date = measured.map(s=>s.verified_progress_date!).sort().at(-1)!;
      if(network.projected_finish_date>date)forecast.push({date,percent},{date:network.projected_finish_date,percent:100});
    }

    return { plan, fact, forecast, today: paused?(fact.at(-1)?.date??network.baseline_finish_date??todayIso):todayIso };
  }, [network, readiness,today,paused]);

  interface RiskRow {
    key: string;
    factor: string;
    message: string;
    severityLabel: string;
    accent: "danger" | "warning" | "ok";
  }
  const riskRows: RiskRow[] = [];
  const coveredStageIds = new Set<string>();
  if (!paused && forecast?.available && forecast.risk_factors) {
    for (const f of forecast.risk_factors) {
      riskRows.push({
        key: `forecast-${f.key}`,
        factor: RISK_KEY_LABEL[f.key] ?? (forecast.work_name ?? "Текущий этап"),
        message: f.message,
        severityLabel: SEVERITY_LABEL[f.severity],
        accent: SEVERITY_ACCENT[f.severity],
      });
    }
    if (forecast.stage_id) coveredStageIds.add(forecast.stage_id);
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

 const planPercent=selected?Math.round(Math.max(0,Math.min(1,(dateStamp(dynamics?.today??today)-dateStamp(selected.planned_start_date))/((durationDays(selected.planned_start_date,selected.planned_end_date)-1||1)*DAY)))*100):0;
 const zoneEvents=events.filter(e=>e.zone_name===zone?.name).slice(0,3);
 return <div className="forecast-analysis">
 <div className="forecast-analysis-top"> <section className="sk-panel forecast-work"><label className="forecast-work-select">Этап для анализа<select aria-label="Этап для анализа" value={selected?.stage_id??''} onChange={e=>{setSelectedId(e.target.value);setTab('overview');}}>{network.stages.filter(s=>!s.is_summary).map(s=><option key={s.stage_id} value={s.stage_id}>{s.work_name}</option>)}</select></label>
 {selected&&<><h2>{selected.work_name}</h2><p className="sk-table__muted">Зона {zone?.name??selected.zone_id} · {paused?'Приостановлен':selected.state_label_ru}</p><div className="forecast-work-tabs"><button aria-pressed={tab==='overview'} onClick={()=>setTab('overview')}>Обзор</button><button aria-pressed={tab==='equipment'} onClick={()=>setTab('equipment')}>Техника</button></div>
 {tab==='overview'?<><h3>Данные о ходе этапа</h3><div className="forecast-stage-metrics"><span>Истекло по плану<b>{planPercent}%</b></span><span>Физический объём<b>{selected.physical_progress_percent==null?'Не измерен':`${selected.physical_progress_percent}%`}</b></span><span>Проверки без отклонений<b>{selected.compliance_percent===null?'—':`${selected.compliance_percent}%`}</b></span></div><p className="sk-table__muted">Ресурсные проверки не измеряют выполненные объёмы. Физический прогресс вводит ответственный в редакторе этапа.</p><h3>Сроки</h3><dl><dt>План</dt><dd>{formatPlanDate(selected.planned_start_date)} — {formatPlanDate(selected.planned_end_date)}</dd><dt>{selected.estimate_kind==='plan_reference_scenario'?'Плановый ориентир':'Сценарная дата'}</dt><dd>{paused?'Приостановлено':formatPlanDate(selected.projected_finish_date)} {!paused&&selected.delay_days>0&&<b>+{selected.delay_days} дн.</b>}</dd></dl><p className="sk-table__muted">Ранний старт {formatPlanDate(selected.early_start_date)}, поздний старт {formatPlanDate(selected.late_start_date)} — запас {selected.total_float_days} дней.</p><div className="forecast-stage-reason"><strong>{selected.state==='overdue'?'Отклонение':'Основание оценки'}</strong><p>{selected.reason||'Нет подтверждающей оценки.'}</p>{checks.filter(c=>!c.satisfied).map(c=><p key={c.class_key}>Недостаточно техники: {c.label_ru} (факт {c.actual_qty} из {c.required_qty})</p>)}</div>{zoneEvents.length>0&&<><h3>Последние события зоны</h3><ul className="forecast-zone-events">{zoneEvents.map(e=><li key={e.id}><time>{new Date(e.created_at).toLocaleTimeString('ru-RU',{timeZone:tz,hour:'2-digit',minute:'2-digit'})}</time><span>{e.title}<small>{e.kind_label_ru}</small></span></li>)}</ul></>}</>:<><StageEquipmentRequirements items={details.find(s=>s.stage_id===selected.stage_id)?.required}/>{checks.length>0&&<div className="forecast-checks">{checks.map(c=><p key={c.class_key}>{c.label_ru}<strong>{c.actual_qty} / {c.required_qty}</strong><span>{c.satisfied?'По требованию':'Недостаточно'}</span></p>)}</div>}</>}
 </>}
 </section></div>
 <section className="sk-panel forecast-dynamics"><h2>Динамика проекта</h2><p className="sk-table__muted">Сценарная линия использует подтверждённые физические объёмы всех работ, взвешенные по плановой длительности. Фотооценка готовности показана отдельно и не определяет дату завершения.</p>{dynamics?<ProjectDynamicsChart showDeadlineSummary={false} {...dynamics} stages={network.stages.filter(s=>!s.is_summary).map(s=>({name:s.work_name,start:s.planned_start_date,end:s.planned_end_date}))} baselineFinish={network.baseline_finish_date} projectedFinish={paused?null:network.projected_finish_date}/>:<p>Недостаточно данных для построения динамики.</p>}</section>
 <div className="forecast-analysis-factors"><section className="sk-panel"><h2>Влияние факторов на прогноз</h2>{!paused&&network.delay_breakdown.available?<><DelayFactorsDonut breakdown={network.delay_breakdown}/><p className="sk-table__muted">{network.delay_breakdown.method_note}</p></>:<p className="sk-table__muted">{paused?'Расчёт будущей задержки отключён: проект приостановлен.':factorsLoading?'Уточняем влияние факторов…':factorsError||'Нет подтверждённого влияния на срок сдачи.'}</p>}</section><section className="sk-panel"><h2>Таблица факторов риска</h2>{riskRows.length?<div className="forecast-risk-scroll"><table className="sk-table"><thead><tr><th>Фактор</th><th>Описание</th><th>Влияние</th></tr></thead><tbody>{riskRows.map(r=><tr key={r.key}><td>{r.factor}</td><td>{r.message}</td><td><span className={`sk-risk-badge sk-risk-badge--${r.accent}`}>{r.severityLabel}</span></td></tr>)}</tbody></table></div>:<p className="sk-table__muted">{paused?'Будущие риски не оцениваются: проект приостановлен.':forecastState==='loading'?'Загружаем оценку рисков…':forecastState==='error'?'Оценка рисков временно недоступна.':forecast?.available===false?forecast.reason||'Недостаточно наблюдений для оценки рисков.':'Подтверждённых факторов риска не выявлено.'}</p>}</section></div>
 {!paused&&<section className="forecast-weather" aria-label="Погодные ограничения на ближайшие 72 часа"><WeatherRiskPanel demoRiskWorkName={network.stages.find(s=>s.state==='in_progress')?.work_name}/></section>}
 </div>;
}
