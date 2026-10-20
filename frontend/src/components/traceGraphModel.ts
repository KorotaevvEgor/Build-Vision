import type {DeviationDetailResponse} from '../api';
import {decisionTrace, type TraceStep} from './decisionTraceModel.ts';
export interface GraphNode extends TraceStep {x:number;y:number;w:number;h:number;tone:string}
export function edgeContribution(from:TraceStep['state'],to:TraceStep['state'],enabled:boolean,supported=true){
 const active=supported&&from==='used'&&to==='used';
 return {active,highlighted:active&&enabled};
}
export function traceGraph(data:DeviationDetailResponse,demo:boolean){
 const steps=decisionTrace(data,demo);
 const nodes:GraphNode[]=[];
 const place=(id:string,x:number,y:number,w:number,h:number,tone:string)=>{nodes.push({...steps.find(s=>s.id===id)!,x,y,w,h,tone});};
 const camera=(id:string,title:string,x:number)=>nodes.push({id,title,x,y:20,w:145,h:100,tone:'blue',subtitle:'Источник кадра',state:demo?'used':'unknown',summary:demo?(id==='camera-a'?'Основной обзор котлована':'Дополнительный ракурс'):'Идентификатор камеры не сохранён',input:demo?'Снимок, время и геометрия обзора.':'Карточка содержит ссылки на снимки, но не содержит достоверного перечня камер.',result:demo?(id==='camera-a'?'Два последовательных наблюдения основной камеры.':'Дополнительный ракурс не увеличивает независимую серию основной камеры.'):'Количество камер по числу снимков не определяется.',impact:'Разные ракурсы не суммируются автоматически: одна машина может попадать в оба обзора.',demo});
 if(demo){camera('camera-a','Камера A',20);camera('camera-b','Камера B',185);}
 else {
  const cameras=new Map<string,typeof data.evidence>();
  for(const e of data.evidence){if(!e.camera_id)continue;const items=cameras.get(e.camera_id)||[];items.push(e);cameras.set(e.camera_id,items);}
  if(!cameras.size)camera('camera-a','Источник снимков',20);
  else {let index=0;for(const [id,items] of cameras){
   nodes.push({id:`camera-${index}`,title:items[0].camera_name||id,x:20+index*165,y:20,w:145,h:100,tone:'blue',subtitle:'Сохранённый источник',state:'used',summary:`Снимков: ${items.length}`,input:items.map(e=>`${e.observation_id} · ${e.captured_at||e.observed_date||'точное время не записано'}`).join('\n'),result:`Камера ${id}. Наблюдения не суммируются с другими ракурсами.`,impact:'Источник связан с этим отклонением через сохранённое наблюдение. Пересекающиеся обзоры не создают дополнительные машины.',demo:false});index++;
  }}
 }
 const cameraIds=nodes.filter(n=>n.id.startsWith('camera-')).map(n=>n.id);
 const cameraHeight=Math.max(0,Math.ceil(cameraIds.length/6)-1)*120;
 for(const [index,n] of nodes.entries()){n.x=20+(index%6)*165;n.y=20+Math.floor(index/6)*120;}
 place('source',20,170,310,130,'blue');
 place('plan',355,170,195,130,'blue');
 const auxiliary=(id:string,title:string,base:string,x:number,tone:string)=>nodes.push({...steps.find(s=>s.id===base)!,id,title,x,y:170,w:195,h:130,tone});
 auxiliary('corrections','Коррекции инженера','learning',575,'violet');
 auxiliary('meteo','Метеоданные','weather',795,'teal');
 place('compare',280,demo?375:585,450,135,'violet');
 place('vision',20,demo?585:375,300,135,'blue');place('learning',355,demo?585:375,300,135,'violet');place('weather',690,demo?585:375,300,135,'teal');
 place('proof',280,790,450,115,'blue');place('decision',280,975,450,125,'amber');
 const visualEvidence=!!data.methodology?.rule?.detector?.execution?.detector||!!data.methodology?.counted_detections?.length;
 const corrected=data.methodology?.rule?.detector?.execution?.correction?.status==='participated';
 const edges=demo?[...cameraIds.map(from=>({from,to:'source',supported:true})),...['source','plan','corrections','meteo'].map(from=>({from,to:'compare',supported:true})),...['vision','learning','weather'].map(to=>({from:'compare',to,supported:true})),...['vision','learning','weather'].map(from=>({from,to:'proof',supported:true})),{from:'proof',to:'decision',supported:true}]:[
 ...cameraIds.map(from=>({from,to:'source',supported:true})),
 {from:'source',to:'vision',supported:true},
 {from:'vision',to:'learning',supported:corrected},
 {from:'corrections',to:'learning',supported:corrected},
 {from:'meteo',to:'weather',supported:false},
 {from:'vision',to:'compare',supported:visualEvidence},
 {from:'learning',to:'compare',supported:corrected},
 {from:'plan',to:'compare',supported:!!data.quantity_checks.length},
 {from:'weather',to:'compare',supported:false},
 {from:'compare',to:'proof',supported:!!data.deviation.proof?.records?.length},
 {from:'proof',to:'decision',supported:!!data.deviation.proof?.records?.length},
 ];
 for(const n of nodes){if(!n.id.startsWith('camera-'))n.y+=cameraHeight;}
 return {nodes,edges,width:1010,height:1120+cameraHeight};
}
