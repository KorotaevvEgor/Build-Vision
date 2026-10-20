import {criticalEdge} from "./criticalPath";
import {useEffect,useId,useMemo,useRef,useState} from 'react';
import type {NetworkStage,StageDetail} from '../api';
import {DAY,dateStamp,durationDays,formatPlanDate} from './scheduleV2Model';
import {scheduleImpact} from './scheduleImpact';
import {StageEquipmentRequirements} from './StageEquipmentRequirements';
import './CalendarNetworkView.css';

interface Props {showCritical?:boolean;details:StageDetail[];stages:NetworkStage[];visible:NetworkStage[];paused:boolean;available:boolean;currentId?:string;onOpen:(id:string)=>void;}
const ROW=70,NAME=250;
export function CalendarNetworkView({showCritical=true,details,stages,visible,paused,available,currentId,onOpen}:Props){
 const [chosen,setChosen]=useState(''),[delay,setDelay]=useState(0),[zoom,setZoom]=useState(0);
 const scroll=useRef<HTMLDivElement>(null);const [containerWidth,setContainerWidth]=useState(1000);
 useEffect(()=>{if(!scroll.current)return;const observer=new ResizeObserver(entries=>setContainerWidth(entries[0].contentRect.width));observer.observe(scroll.current);return()=>observer.disconnect();},[]);
 const selected=stages.find(s=>s.stage_id===chosen)??stages.find(s=>s.stage_id===currentId)??stages.find(s=>!s.is_summary)??stages[0];
 const impact=useMemo(()=>scheduleImpact(stages,selected?.stage_id??'',paused?0:delay),[stages,selected?.stage_id,delay,paused]);
 const timingConflict=impact.available&&stages.some(s=>impact.baseline[s.stage_id]>dateStamp(s.planned_end_date));
 const canSimulate=available&&impact.available&&!paused&&!selected?.is_summary&&!timingConflict;
 const activeDelay=canSimulate?delay:0;
 const ancestors=new Set<string>(),descendants=new Set<string>();
 const visit=(id:string,set:Set<string>,up:boolean)=>{const queue=[id];while(queue.length){const node=queue.pop()!;const next=up?stages.find(s=>s.stage_id===node)?.predecessor_ids??[]:stages.filter(s=>s.predecessor_ids.includes(node)).map(s=>s.stage_id);for(const item of next)if(item!==id&&!set.has(item)){set.add(item);queue.push(item);}}};
 if(selected){visit(selected.stage_id,ancestors,true);visit(selected.stage_id,descendants,false);}
 const from=stages.length?Math.min(...stages.map(s=>dateStamp(s.planned_start_date)))-7*DAY:Date.UTC(2026,0,1);
 const to=stages.length?Math.max(...stages.map(s=>Math.max(dateStamp(s.planned_end_date),activeDelay?impact.ends[s.stage_id]??0:0)))+14*DAY:from+90*DAY;
 const width=Math.min(40000,zoom?Math.max(600,(to-from)/DAY*zoom):Math.max(600,containerWidth-NAME));const ppd=width/((to-from)/DAY);
 const x=(time:number)=>(time-from)/DAY*ppd;
 const quarterTicks=zoom===2||(zoom===0&&ppd<2.4);
 const ticks:{left:number;width:number;label:string}[]=[];let cursor=new Date(from);cursor=new Date(Date.UTC(cursor.getUTCFullYear(),quarterTicks?Math.floor(cursor.getUTCMonth()/3)*3:cursor.getUTCMonth(),1));
 for(let i=0;i<600&&cursor.getTime()<to;i++){const next=new Date(Date.UTC(cursor.getUTCFullYear(),cursor.getUTCMonth()+(quarterTicks?3:1),1));const start=Math.max(from,cursor.getTime()),end=Math.min(to,next.getTime());ticks.push({left:x(start),width:(end-start)/DAY*ppd,label:quarterTicks?`${Math.floor(cursor.getUTCMonth()/3)+1} кв. ${cursor.getUTCFullYear()}`:cursor.toLocaleDateString('ru-RU',{month:'short',year:'2-digit',timeZone:'UTC'})});cursor=next;}
 const marker=`cn-${useId().replaceAll(':','')}`;
 const relation=(id:string)=>id===selected?.stage_id?'selected':ancestors.has(id)?'before':descendants.has(id)?'after':'other';
 const stamp=(time:number)=>new Date(time).toISOString().slice(0,10);
 return <div className="cn">
  <div className="cn-intro"><div><strong>Технологические связи во времени</strong><p>Выберите работу: видны её предшественники и все зависимые этапы.</p></div><label>Масштаб<select value={zoom} onChange={e=>setZoom(Number(e.target.value))}><option value={2}>Кварталы</option><option value={6}>Месяцы</option><option value={18}>Недели</option><option value={0}>Весь план</option></select></label></div>
  {selected&&!visible.some(s=>s.stage_id===selected.stage_id)&&<p className="cn-empty">Выбранная работа скрыта фильтрами. Панель справа показывает её полную цепочку.</p>}
  <div className="cn-layout">
   <div className="cn-scroll" ref={scroll} tabIndex={0} aria-label="Календарно-сетевая диаграмма: сроки и технологические связи">
    <div style={{width:NAME+width}}>
     <div className="cn-axis" style={{width:NAME+width}}><strong style={{width:NAME}}>Работа / технологическая цепочка</strong><div style={{width}}>{ticks.map(t=><span key={t.left} style={{left:t.left,width:t.width}}>{t.width>48?t.label:''}</span>)}</div></div>
     <div className="cn-body" style={{height:visible.length*ROW}}>
      <svg className="cn-links" style={{left:NAME}} width={width} height={visible.length*ROW} aria-hidden="true"><defs><marker id={marker} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 8 4 0 8z" fill="context-stroke"/></marker></defs>{visible.flatMap((s,i)=>s.predecessor_ids.map(id=>{const j=visible.findIndex(p=>p.stage_id===id);if(j<0)return null;const p=visible[j],start=x(dateStamp(p.planned_end_date)+DAY),end=x(dateStamp(s.planned_start_date));const relevant=(id===selected?.stage_id||s.stage_id===selected?.stage_id||ancestors.has(id)&&ancestors.has(s.stage_id)||descendants.has(id)&&descendants.has(s.stage_id));return <path key={`${id}-${s.stage_id}`} className={showCritical&&criticalEdge(p,s)?'is-critical':relevant?'is-chain':''} d={`M${start},${j*ROW+27} C${start+20},${j*ROW+27} ${end-20},${i*ROW+27} ${end},${i*ROW+27}`} markerEnd={`url(#${marker})`}/>;}))}</svg>
      {visible.map(s=>{const start=x(dateStamp(s.planned_start_date)),barWidth=durationDays(s.planned_start_date,s.planned_end_date)*ppd;const shifted=activeDelay?(impact.shifts[s.stage_id]??0):0;return <div key={s.stage_id} className={`cn-row cn-row--${relation(s.stage_id)}`} style={{height:ROW}}><button className="cn-name" style={{width:NAME}} onClick={()=>setChosen(s.stage_id)} aria-pressed={selected?.stage_id===s.stage_id}><small>{s.work_code||'Работа'} · {durationDays(s.planned_start_date,s.planned_end_date)} дн.</small><strong title={s.work_name}>{s.work_name}</strong></button><div className="cn-track" style={{width}}>{ticks.map(t=><i key={t.left} style={{left:t.left}}/>)}<button className={`cn-bar ${showCritical&&s.is_critical?'is-critical':''}`} style={{left:start,width:Math.max(5,barWidth)}} onClick={()=>setChosen(s.stage_id)} title={`${s.work_name}: ${formatPlanDate(s.planned_start_date)} — ${formatPlanDate(s.planned_end_date)}`} aria-label={`Выбрать работу ${s.work_name}`}><span>{barWidth>60?`${durationDays(s.planned_start_date,s.planned_end_date)} дн.`:''}</span></button>{canSimulate&&s.total_float_days>0&&<span className="cn-reserve" style={{left:start+barWidth,width:Math.min(s.total_float_days*ppd,width-start-barWidth)}} title={`Резерв времени: ${s.total_float_days} дн.`}/>} {shifted>0&&<span className="cn-scenario" style={{left:x(impact.ends[s.stage_id]- (durationDays(s.planned_start_date,s.planned_end_date)+(s.stage_id===selected?.stage_id?activeDelay:0)-1)*DAY),width:barWidth+(s.stage_id===selected?.stage_id?activeDelay*ppd:0)}} title={`Сценарий: окончание ${formatPlanDate(stamp(impact.ends[s.stage_id]))}`}><b>+{shifted} дн.</b></span>}</div></div>;})}
     </div>
    </div>
    {!visible.length&&<p className="cn-empty">Нет работ для отображения. Проверьте фильтры.</p>}
   </div>
   <aside className="cn-inspector" aria-label="Влияние выбранной работы">
    {selected?<><small>ВЫБРАННАЯ РАБОТА</small><h3>{selected.work_name}</h3><div className="cn-facts"><span>Начало<b>{formatPlanDate(selected.planned_start_date)}</b></span><span>Окончание<b>{formatPlanDate(selected.planned_end_date)}</b></span><span>Продолжительность<b>{durationDays(selected.planned_start_date,selected.planned_end_date)} дн.</b></span><span>Резерв по расчёту<b>{available?`${selected.total_float_days} дн.`:'Нет расчёта'}</b></span><span>Зависимых работ<b>{descendants.size}</b></span></div>
     <section><h4>Необходимая техника</h4><StageEquipmentRequirements items={details.find(s=>s.stage_id===selected.stage_id)?.required}/></section>
     <button className="cn-edit" onClick={()=>onOpen(selected.stage_id)}>Открыть работу и редактировать</button>
     <section><h4>Влияние сдвига сроков</h4><label>Увеличить длительность на <input aria-label="Сценарная задержка, дней" type="number" min="0" max="365" step="1" disabled={!canSimulate} value={delay} onChange={e=>setDelay(Math.min(365,Math.max(0,Math.round(Number(e.target.value)||0))))}/> дн.</label>{canSimulate?<><div className="cn-impact"><span>Сдвиг завершения проекта<strong>+{impact.finishShift} дн.</strong></span><span>Сдвинется следующих работ<strong>{impact.affected.length}</strong></span></div>{activeDelay>0&&<button className="cn-reset" onClick={()=>setDelay(0)}>Сбросить сценарий</button>}<p>Расчётный сценарий по связям «окончание → начало» и календарным дням. Учитывает промежутки между работами, не меняет сохранённый план и не является прогнозом.</p></>:<p>{paused?'Проект приостановлен. Моделирование срока сдачи отключено.':selected?.is_summary?'Для сценария выберите отдельную работу, а не сводный этап.':timingConflict?'В исходном плане зависимые работы пересекаются по датам. Уточните связи или даты перед моделированием.':'Для сценария нужен корректный сетевой расчёт.'}</p>}</section>
     <section><h4>Что зависит от этой работы</h4>{descendants.size?<ul>{stages.filter(s=>descendants.has(s.stage_id)).map(s=><li key={s.stage_id}><button onClick={()=>setChosen(s.stage_id)}>{s.work_name}</button>{activeDelay>0&&<b>{impact.shifts[s.stage_id]?`+${impact.shifts[s.stage_id]} дн.`:'Без сдвига'}</b>}</li>)}</ul>:<p>Последующие работы не связаны с этим этапом.</p>}</section>
    </>:<p>В проекте пока нет работ.</p>}
   </aside>
  </div>
  <div className="cn-legend"><span><i className="cn-key-before"/>Предшественники</span><span><i className="cn-key-selected"/>Выбранная работа</span><span><i className="cn-key-after"/>Зависимые работы</span><span><i className="cn-key-reserve"/>Резерв</span>{activeDelay>0&&<span><i className="cn-key-scenario"/>Сценарий сдвига</span>}{showCritical&&<span>Красные стрелки и полосы — критический путь</span>}</div>
 </div>;
}
