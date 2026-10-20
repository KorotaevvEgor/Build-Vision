import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchAnalytics, fetchDashboard, fetchDeviations, fetchReadiness, fetchStages,
  type AnalyticsResponse, type DashboardResponse, type DeviationRecord, type ReadinessResponse, type StageDetail } from "../api";
import { useProject } from "../ProjectContext";
import "./PausedSchedulePage.css";

type Data = { dashboard: DashboardResponse; readiness: ReadinessResponse; stages: StageDetail[]; deviations: DeviationRecord[]; analytics: AnalyticsResponse };
const dateLabel = (iso: string) => new Date(iso).toLocaleDateString("ru-RU", {day:"2-digit",month:"2-digit",year:"numeric"});
const stamp = (iso: string) => new Date(iso).getTime();
const duration = (s: StageDetail) => Math.round((stamp(s.end_date)-stamp(s.start_date))/86400000)+1;

export function PausedSchedulePage() {
  const { projectId, project } = useProject();
  const [data,setData]=useState<Data|null>(null);
  const [error,setError]=useState("");
  const [view,setView]=useState<"gantt"|"table">("gantt");
  const [selected,setSelected]=useState<string|null>(null);
  const [session,setSession]=useState<string|null>(null);
  useEffect(()=>{
    let active=true;
    Promise.all([fetchReadiness(projectId),fetchStages(projectId),fetchDeviations(projectId),fetchAnalytics(projectId,0),fetchDashboard(projectId)])
      .then(([readiness,stages,deviations,analytics,dashboard])=>{if(active)setData({readiness,stages:stages.stages,deviations:deviations.items,analytics,dashboard});})
      .catch((e:Error)=>{if(active)setError(e.message);});
    return ()=>{active=false;};
  },[projectId]);
  const facts=useMemo(()=>[...(data?.readiness.fact??[])].sort((a,b)=>a.date.localeCompare(b.date)),[data]);
  if(error)return <div className="sk-panel sk-panel--error">Не удалось загрузить план: {error}</div>;
  if(!data)return <div className="sk-panel">Загрузка календарного плана…</div>;
  const last=facts.at(-1);
  const lastPhoto=data.dashboard.last_observed_date??null;
  const end=lastPhoto??data.stages.map(s=>s.end_date).sort().at(-1)??new Date().toISOString().slice(0,10);
  const sorted=[...data.stages].sort((a,b)=>a.start_date.localeCompare(b.start_date)||a.work_code.localeCompare(b.work_code));
  const first=sorted[0]?.start_date??end;
  const current=sorted.find(s=>s.stage_id===data.dashboard.current_stage?.stage_id);
  const focused=sorted.find(s=>s.stage_id===selected)??current;
  const open=data.deviations.filter(d=>["detected","assigned","confirmed"].includes(d.status));
  const categories=[
    {key:"equipment",label:"Состав техники",color:"#f6bc73",count:open.filter(d=>d.kind.includes("equipment")||d.kind.includes("missing")).length},
    {key:"stage",label:"Стадия и готовность",color:"#a797ec",count:open.filter(d=>!d.kind.includes("equipment")&&!d.kind.includes("missing")).length},
  ];
  const total=categories.reduce((sum,c)=>sum+c.count,0);
  const span=Math.max(stamp(end)-stamp(first),86400000);
  const ganttEnd=[end,...sorted.map(s=>s.end_date)].sort().at(-1)??end;
  const ganttSpan=Math.max(stamp(ganttEnd)-stamp(first),86400000);
  const x=(iso:string)=>58+(stamp(iso)-stamp(first))/span*910;
  const ceiling=Math.max(20,Math.ceil(Math.max(...facts.map(p=>p.readiness_percent),0)/10)*10);
  const y=(n:number)=>225-n/ceiling*175;
  const line=facts.map(p=>`${x(p.date)},${y(p.readiness_percent)}`).join(" ");
  const inspected=facts.find(p=>p.date===session)??last;
  const months=Array.from(new Set(facts.map(p=>p.date.slice(0,7))));
  const ganttMonths=[];
  for(let d=new Date(first.slice(0,7)+"-01T00:00:00Z");d.getTime()<=stamp(ganttEnd);d.setUTCMonth(d.getUTCMonth()+1)) {
    ganttMonths.push({key:d.toISOString(),label:d.toLocaleDateString("ru-RU",{month:"long",timeZone:"UTC"})});
  }
  const table=<div className="paused-table-wrap"><table className="paused-table">
    <thead><tr><th>Работа</th><th>Начало</th><th>Окончание</th><th>Дней</th><th>Плановая техника</th><th>Статус</th></tr></thead>
    <tbody>{sorted.map(s=><tr key={s.stage_id} className={s.stage_id===current?.stage_id?"is-current":""} onClick={()=>setSelected(s.stage_id)}>
      <td><span className="paused-code">{s.work_code}</span><strong>{s.work_name}</strong></td>
      <td>{dateLabel(s.start_date)}</td><td>{dateLabel(s.end_date)}</td><td>{duration(s)}</td>
      <td>{s.required.map(q=><span className="paused-eq-chip" key={q.class_key}>{q.label_ru} ×{q.min_quantity}</span>)}{s.technology_assumption.includes("Ручной контроль")&&<small>Дополнительная техника — в примечании</small>}</td>
      <td><span className={`paused-row-status ${s.stage_id===current?.stage_id?"is-paused":""}`}>{s.stage_id===current?.stage_id?"Остановлен":!lastPhoto||s.start_date>lastPhoto?"Нет фото":"Архив плана"}</span></td>
    </tr>)}</tbody></table></div>;
  return <main className="paused-schedule">
    <header className="paused-heading"><div><div className="paused-eyebrow">КАЛЕНДАРНЫЙ ПЛАН</div><h1>Работы приостановлены</h1><p>{project.name} <span>·</span> {project.address}</p></div><span className="paused-status"><i/>Проект приостановлен</span></header>
    <div className="paused-kpis">
      <article className="paused-kpi paused-kpi--deadline"><span>Срок сдачи объекта</span><strong>Приостановлено</strong><small>Новая дата после возобновления работ</small></article>
      <article className="paused-kpi"><span>Последний фотоконтроль</span><strong>{lastPhoto?dateLabel(lastPhoto):"Нет фото"}</strong><small>{data.analytics.total_observations} кадров в истории проекта</small></article>
      <article className="paused-kpi"><span>Готовность по фото</span><strong>{last?.readiness_percent.toLocaleString("ru-RU")??"—"}<em>%</em></strong><small>Визуальная оценка, не приёмка работ</small></article>
      <article className="paused-kpi"><span>Календарный план</span><strong>{sorted.length}<em>работ</em></strong><small>{dateLabel(first)} — {dateLabel(end)}</small></article>
    </div>
    <section className="paused-last-stage"><div className="paused-last-stage__mark"/><div><span>ЭТАП НА МОМЕНТ ОСТАНОВКИ</span><h2>{current?.work_name??"Этап требует уточнения"}</h2><p>{lastPhoto?`По графику на дату последнего подтверждённого кадра — ${dateLabel(lastPhoto)}.`:"Подтверждённых снимков для определения последнего этапа нет."} Продолжение и завершение работ не подтверждены.</p></div><Link to={`/projects/${projectId}`}>Смотреть кадры <b>↗</b></Link></section>
    <div className="paused-charts">
      <section className="paused-panel paused-dynamics"><div className="paused-panel-heading"><div><h2>Динамика проекта</h2><p>Готовность по фотообходам до остановки</p></div><span className="paused-live-dot">Фотофакт</span></div>
        <div className="paused-chart-summary"><strong>{inspected?.readiness_percent.toLocaleString("ru-RU")??"—"}<small>%</small></strong><span>{inspected?dateLabel(inspected.date):"Нет фотооценки"}<br/><small>{inspected?.frames??0} кадров в обходе</small></span></div>
        <svg className="paused-line-chart" viewBox="0 0 1000 275" role="img" aria-label="Динамика визуальной готовности по датам фотографий">
          <defs><linearGradient id="paused-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#57d2b9" stopOpacity=".2"/><stop offset="100%" stopColor="#57d2b9" stopOpacity="0"/></linearGradient></defs>
          {[0,ceiling/2,ceiling].map(n=><g key={n}><line x1="58" y1={y(n)} x2="968" y2={y(n)} stroke="#ffffff0d" strokeDasharray="4 6"/><text x="41" y={y(n)+4} textAnchor="end">{n}%</text></g>)}
          {facts.length>0&&<polygon points={`${x(facts[0].date)},225 ${line} ${x(end)},225`} fill="url(#paused-area)"/>}
          <polyline points={line} fill="none" stroke="#57d2b9" strokeWidth="3" strokeLinejoin="round"/>
          <line x1={x(end)} y1="35" x2={x(end)} y2="231" stroke="#efb966" strokeDasharray="5 5"/>
          {facts.map(p=><circle key={p.date} cx={x(p.date)} cy={y(p.readiness_percent)} r={session===p.date?7:5} fill="#121c29" stroke="#67dfc5" strokeWidth="3" onMouseEnter={()=>setSession(p.date)} onFocus={()=>setSession(p.date)} tabIndex={0}><title>{dateLabel(p.date)}: {p.readiness_percent}%</title></circle>)}
          {months.map(m=>{const p=facts.find(f=>f.date.startsWith(m))!;return <text key={m} x={Math.max(64,Math.min(940,x(p.date)))} y="257" textAnchor="middle">{new Date(p.date).toLocaleDateString("ru-RU",{month:"short"})}</text>;})}
        </svg><p className="paused-chart-note">Оценки разных ракурсов могут различаться. Прогнозная линия на период приостановки не строится.</p>
      </section>
      <section className="paused-panel paused-factors"><div className="paused-panel-heading"><div><h2>Влияние факторов</h2><p>Открытые предупреждения фотоконтроля</p></div></div>
        <div className="paused-factor-ring"><svg viewBox="0 0 140 140" role="img" aria-label={`${total} открытых предупреждений`}><circle cx="70" cy="70" r="54" fill="none" stroke="#ffffff08" strokeWidth="12"/>{categories.map((c,i)=>{const prev=categories.slice(0,i).reduce((sum,a)=>sum+a.count,0);return <circle key={c.key} cx="70" cy="70" r="54" fill="none" stroke={c.color} strokeWidth="12" strokeDasharray={`${total?c.count/total*339.3:0} 339.3`} strokeDashoffset={total?-prev/total*339.3:0} transform="rotate(-90 70 70)"/>;})}</svg><div><strong>{total}</strong><span>предупреждения</span></div></div>
        <div className="paused-factor-list">{categories.map(c=><div key={c.key}><i style={{background:c.color}}/><span>{c.label}</span><strong>{c.count}</strong></div>)}</div>
        <p className="paused-factor-note">Причина приостановки не указана. Предупреждения не определяют её причину и не дают дату возобновления.</p>
      </section>
    </div>
    <section className="paused-panel paused-plan"><div className="paused-panel-heading"><div><h2>Календарный график</h2><p>{sorted.length} работ · периоды из календарного плана</p></div><div className="paused-tabs"><button className={view==="gantt"?"is-active":""} onClick={()=>setView("gantt")}>Гантт</button><button className={view==="table"?"is-active":""} onClick={()=>setView("table")}>Таблица</button></div></div>
      {view==="table"?table:<div className="paused-gantt-scroll"><div className="paused-gantt"><div className="paused-gantt-head"><span>Наименование работ</span><div style={{gridTemplateColumns:`repeat(${ganttMonths.length},1fr)`}}>{ganttMonths.map(m=><span key={m.key}>{m.label}</span>)}</div></div>{sorted.map(s=>{const left=(stamp(s.start_date)-stamp(first))/ganttSpan*100;const width=Math.max(.7,(stamp(s.end_date)-stamp(s.start_date))/ganttSpan*100);return <button key={s.stage_id} className={`paused-gantt-row ${s.stage_id===focused?.stage_id?"is-selected":""}`} onClick={()=>setSelected(s.stage_id)}><span><small>{s.work_code}</small>{s.work_name}</span><div className="paused-gantt-track"><i className={s.stage_id===current?.stage_id?"is-paused":!lastPhoto||s.start_date>lastPhoto?"is-planned":""} style={{left:`${Math.min(left,99)}%`,width:`${width}%`,minWidth:6}} title={`${dateLabel(s.start_date)} — ${dateLabel(s.end_date)}`}/></div></button>;})}</div></div>}
      <div className="paused-plan-legend"><span><i/>Интервал по плану</span><span><i className="is-paused"/>Последний зафиксированный этап</span></div>
    </section>
    {focused&&<section className="paused-panel paused-detail"><div><span className="paused-eyebrow">{focused.work_code} · ПРИМЕЧАНИЕ К РАБОТЕ</span><h2>{focused.work_name}</h2><p>{focused.technology_assumption.split("\n")[0]}</p></div><span>{dateLabel(focused.start_date)}<br/>{dateLabel(focused.end_date)}</span></section>}
    <section className="paused-conclusions"><h2>Выводы по проекту</h2><div><article><span>01</span><h3>Работы на паузе</h3><p>Статус проекта — «Приостановлен». Срок сдачи появится после утверждения графика возобновления.</p></article><article><span>02</span><h3>Последний зафиксированный этап</h3><p>{lastPhoto?`Контрольная дата — ${dateLabel(lastPhoto)}.`:"Контрольная дата не определена."} Последняя работа: {current?.work_name.toLowerCase()??"требует уточнения"}.</p></article><article><span>03</span><h3>Перед возобновлением</h3><p>Нужны новый фотообход, проверка сохранности площадки и актуализация техники и сроков. Исторические оценки не подтверждают сегодняшнюю готовность.</p></article></div></section>
  </main>;
}
