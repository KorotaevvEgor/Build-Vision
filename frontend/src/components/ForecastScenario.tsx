import {useState} from 'react';
import type {ScheduleNetworkResponse} from '../api';
import {scenarioFinish} from './forecastScenarioModel';
import {formatPlanDate} from './scheduleV2Model';
import './ForecastScenario.css';

const assumptions = [
  {suffix:'future-1',name:'Темп монолитных работ',days:12,recovery:8,reason:'В расчёте принят дефицит подачи материалов и снижение темпа монолита.',action:'Дополнительная смена и согласованный график подачи бетона',color:'#e05465'},
  {suffix:'future-2',name:'Фасадные работы',days:4,recovery:2,reason:'Заложен перерыв между поставкой материалов и началом монтажа.',action:'Комплектная поставка материалов до начала монтажа',color:'#e99a35'},
  {suffix:'future-3',name:'Кровля и инженерные системы',days:2,recovery:1,reason:'Принято двухдневное окно ограничений наружных работ.',action:'Перенос наружных операций и защита рабочих зон',color:'#7168db'},
  {suffix:'aux-06',name:'Поставка фасадных материалов',days:10,recovery:0,reason:'Сдвиг поставки на 10 дней поглощается резервом этой работы.',action:'Контроль срока поставки: ускорение пока не требуется',color:'#329eab'},
];

export function ForecastScenario({network}:{network:ScheduleNetworkResponse}) {
  const [enabled,setEnabled]=useState<string[]>([]);
  const inputs=assumptions.map(a=>({...a,stage:network.stages.find(s=>s.stage_id===`site39-stage-${a.suffix}`)}));
  if(inputs.some(i=>!i.stage))return null;
  let baseline:string,before:string,after:string;
  try {
    baseline=scenarioFinish(network.stages,{});
    before=scenarioFinish(network.stages,Object.fromEntries(inputs.map(i=>[i.stage!.stage_id,i.days])));
    after=scenarioFinish(network.stages,Object.fromEntries(inputs.map(i=>[i.stage!.stage_id,i.days-(enabled.includes(i.suffix)?i.recovery:0)])));
  } catch {return <section className="sk-insight-card"><h2>Сценарий восстановления графика</h2><p>Пересчёт недоступен: проверьте даты и зависимости работ в календарном плане.</p></section>;}
  const delta=(a:string,b:string)=>Math.round((Date.parse(a)-Date.parse(b))/86400000);
  const beforeDays=delta(before,baseline),afterDays=delta(after,baseline),saved=beforeDays-afterDays;
  return <section className="fs-scenario" aria-labelledby="fs-title">
    <header><div><span className="fs-eyebrow">Управление сроками</span><h2 id="fs-title">Как вернуть график под контроль</h2><p>Расчётный сценарий по зависимостям календарного плана. Выберите меры и сравните результат.</p></div><button onClick={()=>setEnabled(saved?[]:inputs.filter(i=>i.recovery).map(i=>i.suffix))}>{saved?'Сбросить меры':'Применить все меры'}</button></header>
    <div className="fs-metrics" aria-live="polite"><div><span>Плановая сдача</span><strong>{formatPlanDate(baseline)}</strong><small>Базовый график · {network.stages.filter(s=>s.is_critical&&!s.is_summary).length} критических работ</small></div><div className="fs-danger"><span>Без дополнительных мер</span><strong>+{beforeDays} дней</strong><small>Сдача {formatPlanDate(before)}</small></div><div className="fs-result"><span>После выбранных мер</span><strong>+{afterDays} дней</strong><small>Сдача {formatPlanDate(after)}</small></div><div className="fs-result"><span>Возвращаем в график</span><strong>{saved} дней</strong><small>Потенциал предложенных мер — до 11 дней</small></div></div>
    <div className="fs-columns"><section className="fs-factors"><h3>Откуда складывается задержка</h3><p>Вклад в срок сдачи после учёта запаса времени</p>{inputs.map(i=>{const impact=i.stage!.is_critical?i.days-(enabled.includes(i.suffix)?i.recovery:0):Math.max(0,i.days-i.stage!.total_float_days);return <div className="fs-factor" key={i.suffix}><div><span>{i.name}</span><b>{impact?`+${impact} дн.`:'В резерве'}</b></div><div className="fs-track"><i style={{width:`${impact/12*100}%`,background:i.color}}/></div><small>{i.recovery?i.reason:`Сдвиг ${i.days} дней · запас ${i.stage!.total_float_days} дней · сдача не меняется`}</small></div>})}<div className="fs-equation">Критическая цепочка: монолит → фасад → кровля и инженерные системы → отделка и благоустройство</div></section>
    <section className="fs-actions"><h3>Меры по восстановлению</h3><p>Эффект пересчитывается сразу; исходный план сохраняется</p>{inputs.filter(i=>i.recovery).map(i=><label key={i.suffix} className={enabled.includes(i.suffix)?'is-active':''}><input type="checkbox" checked={enabled.includes(i.suffix)} onChange={e=>setEnabled(v=>e.target.checked?[...v,i.suffix]:v.filter(x=>x!==i.suffix))}/><span><strong>{i.action}</strong><small>{i.stage!.work_name}</small></span><b>−{i.recovery} дн.</b></label>)}<div className="fs-outcome" role="status"><strong>{saved?`Выбранные меры сокращают задержку на ${saved} дней`:'Выберите меры, чтобы увидеть эффект'}</strong><p>{saved?`Остаточный сдвиг — ${afterDays} дней. Для возврата к плановой дате нужны дополнительные решения по критической цепочке.`:'Система учитывает последовательность работ: задержки на критической цепочке передаются следующим этапам.'}</p></div></section></div>
    <details className="fs-assumptions"><summary>Условия и исходные допущения расчёта</summary><p>Приняты дополнительные длительности: монолит +12, фасад +4, кровля и инженерные системы +2, поставка фасадных материалов +10 календарных дней. Эффект мер: 8, 2 и 1 день соответственно. Эти значения задают сценарий, не являются замерами выполненных объёмов или фактической погодой. Связи «окончание–начало», без ресурсного выравнивания; стоимость, возможность дополнительной смены и технологические ограничения согласует инженер. Показатели наблюдений ниже загружаются отдельно из системы.</p></details>
  </section>;
}
