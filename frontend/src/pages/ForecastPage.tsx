import {useEffect,useState} from "react";
import {Link} from "react-router-dom";
import {fetchScheduleNetwork,fetchStageForecast,type ForecastResponse,type ScheduleNetworkResponse} from "../api";
import {useProject} from "../ProjectContext";
import {ForecastScenario} from "../components/ForecastScenario";
import {ForecastAnalysis} from "../components/ForecastAnalysis";
import {formatPlanDate} from "../components/scheduleV2Model";
import "./ForecastPage.css";
import "./InsightsPage.css";
export function ForecastPage({embedded=false}:{embedded?:boolean}={}){
 const {projectId,project}=useProject(),paused=project.status==="paused";
 const [network,setNetwork]=useState<ScheduleNetworkResponse|null>(null),[forecast,setForecast]=useState<ForecastResponse|null>(null),[error,setError]=useState(""),[factorsLoading,setFactorsLoading]=useState(false),[factorsError,setFactorsError]=useState(""),[forecastState,setForecastState]=useState<"loading"|"ready"|"error">("loading");
 useEffect(()=>{let active=true;setNetwork(null);setForecast(null);setForecastState("loading");setError("");setFactorsError("");setFactorsLoading(!paused);
 fetchScheduleNetwork(projectId,false).then(n=>{if(!active)return;setNetwork(n);if(!paused)fetchScheduleNetwork(projectId).then(full=>active&&setNetwork(full)).catch(()=>active&&setFactorsError("Не удалось уточнить влияние факторов. Основной график рассчитан по плану и подтверждённым объёмам.")).finally(()=>active&&setFactorsLoading(false));}).catch(e=>{if(active){setError(e.message);setFactorsLoading(false);}});
 fetchStageForecast(projectId).then(f=>{if(active){setForecast(f);setForecastState("ready");}}).catch(()=>active&&setForecastState("error"));return()=>{active=false;};},[projectId,paused]);
 if(error)return <div className="sk-panel sk-panel--error" role="alert">Не удалось загрузить прогноз: {error}</div>;
 if(!network)return <div className="sk-panel" role="status">Расчёт сроков по календарному плану…</div>;
 if(!network.available)return <section className="sk-insight-card"><h2>Расчёт сроков недоступен</h2><p>{network.reason}</p><Link className="sk-back-button" to={`/projects/${projectId}/schedule`}>Проверить связи работ →</Link></section>;
 const shifting=paused?[]:network.stages.filter(s=>s.shifts_project_finish&&!s.is_summary);
 return <div className="sk-forecast-page" id="sk-forecast-print-area">{!embedded&&<h1>Прогноз сроков</h1>}{String(projectId)==="39"&&!paused&&<ForecastScenario key={projectId} network={network}/>}<div className="sk-insight-metrics"><div className="sk-insight-metric"><span>Плановая сдача</span><strong>{formatPlanDate(network.baseline_finish_date??"")}</strong><small>По календарному плану</small></div><div className={`sk-insight-metric sk-insight-metric--${paused?"warning":network.shift_days>0?"danger":"normal"}`}><span>Сценарная дата сдачи</span><strong>{paused?"Приостановлено":formatPlanDate(network.projected_finish_date??"")}</strong><small>{paused?"Новая дата не рассчитывается":network.estimate_kind==="plan_reference_scenario"?"Только план: физических замеров нет":"Оценка по замерам и ожидаемым датам"}</small></div><div className="sk-insight-metric sk-insight-metric--danger"><span>Сдвиг к плану</span><strong>{paused?"—":`${network.shift_days>0?"+":""}${network.shift_days} дн.`}</strong><small>{paused?"Проект на паузе":network.shift_days>0?"Превышен запас времени":"Нулевой сдвиг не подтверждает выполнение"}</small></div><div className="sk-insight-metric"><span>Работы, влияющие на сдачу</span><strong>{paused?"—":shifting.length}</strong><small>{network.unverified_stage_ids.length>0?`${network.unverified_stage_ids.length} работ без подтверждения по снимкам`:"По расчёту критического пути"}</small></div></div>
 {paused&&<p className="sk-insight-note">Проект приостановлен. Показана история наблюдений; будущая дата сдачи не прогнозируется.</p>}
 <ForecastAnalysis network={network} forecast={forecast} factorsLoading={factorsLoading} factorsError={factorsError} forecastState={forecastState}/>
 {network.unverified_stage_ids.length>0&&<details className="sk-insight-card"><summary>Работы без подтверждения по снимкам · {network.unverified_stage_ids.length}</summary><p>Плановый срок истёк, но завершение не подтверждено ответственным лицом. Наличие техники на снимке не подтверждает выполнение работ.</p><ul>{network.stages.filter(s=>network.unverified_stage_ids.includes(s.stage_id)).map(s=><li key={s.stage_id}>{s.work_name} · план до {formatPlanDate(s.planned_end_date)}</li>)}</ul></details>}
 <p className="sk-insight-note">Методика: ожидаемое окончание ответственного или сценарий сохранения измеренного физического темпа. Без замеров используется плановая дата. Сдвиг сверх временного резерва переносится по технологическим связям работ. Доли успешных проверок и оценка готовности по фото не заменяют приёмку физических объёмов. <Link to={`/projects/${projectId}/forecast/why`}>Как рассчитан прогноз →</Link></p></div>;
}
