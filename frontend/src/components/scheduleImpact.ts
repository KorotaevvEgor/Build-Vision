const DAY=86400000;
interface Work {stage_id:string;planned_start_date:string;planned_end_date:string;predecessor_ids:string[];is_summary:boolean;}
/** A local finish-to-start scenario. Compare against the same zero-delay calculation,
 * so pre-existing inconsistencies never become an invented effect of the scenario. */
export function scheduleImpact(stages:Work[],selected:string,days:number){
 const byId=new Map(stages.map(s=>[s.stage_id,s]));
 const successors=new Map<string,string[]>(),degree=new Map<string,number>();
 for(const s of stages){const deps=[...new Set(s.predecessor_ids)].filter(id=>byId.has(id));degree.set(s.stage_id,deps.length);for(const id of deps)successors.set(id,[...(successors.get(id)??[]),s.stage_id]);}
 const order=stages.filter(s=>degree.get(s.stage_id)===0).map(s=>s.stage_id);
 for(let i=0;i<order.length;i++)for(const id of successors.get(order[i])??[]){degree.set(id,degree.get(id)!-1);if(degree.get(id)===0)order.push(id);}
 const valid=order.length===stages.length&&stages.every(s=>Number.isFinite(Date.parse(s.planned_start_date))&&Date.parse(s.planned_end_date)>=Date.parse(s.planned_start_date));
 const baseline:Record<string,number>={},ends:Record<string,number>={},shifts:Record<string,number>={};
 if(!valid)return {available:false,baseline,ends,shifts,finishShift:0,affected:[] as string[]};
 for(const id of order){const s=byId.get(id)!;const start=Date.parse(s.planned_start_date),duration=Date.parse(s.planned_end_date)-start;const deps=s.predecessor_ids.filter(p=>byId.has(p));const baseStart=Math.max(start,...deps.map(p=>baseline[p]+DAY));const changedStart=Math.max(start,...deps.map(p=>ends[p]+DAY));baseline[id]=baseStart+duration;ends[id]=changedStart+duration+(id===selected?Math.max(0,days)*DAY:0);shifts[id]=Math.round((ends[id]-baseline[id])/DAY);}
 const leaves=stages.filter(s=>!s.is_summary);const finish=(values:Record<string,number>)=>Math.max(0,...leaves.map(s=>values[s.stage_id]));
 return {available:true,baseline,ends,shifts,finishShift:Math.round((finish(ends)-finish(baseline))/DAY),affected:order.filter(id=>id!==selected&&shifts[id]>0)};
}
export function scheduleSignal(s:{state:string;delay_days:number;total_float_days:number;observation_count:number}){
 if(s.state==='done_on_time')return {tone:'ok',label:'Завершено в срок'};
 if(s.delay_days>0)return s.delay_days>Math.max(0,s.total_float_days)?{tone:'danger',label:'Отставание превышает резерв'}:{tone:'warning',label:'Отставание в пределах резерва'};
 if(s.state==='unverified'||!s.observation_count)return {tone:'neutral',label:s.state==='not_started'?'Запланировано':'Нет подтверждения'};
 if(s.state==='overdue')return {tone:'danger',label:'Срок нарушен'};
 return {tone:'ok',label:'По графику'};
}
