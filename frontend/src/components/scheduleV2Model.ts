import type { NetworkStage } from "../api";
export const DAY = 86400000;
export const dateStamp=(iso:string)=>Date.parse(`${iso}T00:00:00Z`);
export const formatPlanDate=(iso:string)=>Number.isFinite(dateStamp(iso))?new Date(dateStamp(iso)).toLocaleDateString("ru-RU",{timeZone:"UTC"}):"—";
export const durationDays=(start:string,end:string)=>Math.max(1,Math.round((dateStamp(end)-dateStamp(start))/DAY)+1);
export interface ScheduleRow {stage:NetworkStage;depth:number;outline:string;hasChildren:boolean;}
export function scheduleRows(stages:NetworkStage[],collapsed:Set<string>,match?:(stage:NetworkStage)=>boolean):ScheduleRow[] {
 const byId=new Map(stages.map(s=>[s.stage_id,s]));
 const children=new Map<string|null,NetworkStage[]>();
 for(const stage of stages){const parent=stage.parent_id&&byId.has(stage.parent_id)?stage.parent_id:null;children.set(parent,[...(children.get(parent)??[]),stage]);}
 for(const items of children.values())items.sort((a,b)=>a.planned_start_date.localeCompare(b.planned_start_date));
 const included=new Set<string>();
 if(match)for(const stage of stages)if(match(stage)){let node:NetworkStage|undefined=stage;const visited=new Set<string>();while(node&&!visited.has(node.stage_id)){included.add(node.stage_id);visited.add(node.stage_id);node=node.parent_id?byId.get(node.parent_id):undefined;}}
 const rows:ScheduleRow[]=[];const visited=new Set<string>();
 const visit=(stage:NetworkStage,depth:number,outline:string)=>{if(visited.has(stage.stage_id))return;visited.add(stage.stage_id);if(match&&!included.has(stage.stage_id))return;const sub=children.get(stage.stage_id)??[];rows.push({stage,depth,outline,hasChildren:sub.length>0});if(!collapsed.has(stage.stage_id)||match)sub.forEach((s,i)=>visit(s,depth+1,`${outline}.${i+1}`));};
 (children.get(null)??[]).forEach((s,i)=>visit(s,0,String(i+1)));
 // Recover malformed/orphan cycles without dropping rows or looping forever.
 const reachable=new Set<string>();const pending=[...(children.get(null)??[])];while(pending.length){const node=pending.pop()!;if(reachable.has(node.stage_id))continue;reachable.add(node.stage_id);pending.push(...(children.get(node.stage_id)??[]));}
 for(const stage of stages)if(!reachable.has(stage.stage_id)&&!visited.has(stage.stage_id))visit(stage,0,String(rows.length+1));
 return rows;
}
export function timelineGeometry(stages:NetworkStage[],pixelsPerDay:number,available:number,paused:boolean){
 const valid=stages.filter(s=>Number.isFinite(dateStamp(s.planned_start_date))&&Number.isFinite(dateStamp(s.planned_end_date)));
 const from=valid.length?Math.min(...valid.map(s=>dateStamp(s.planned_start_date)))-DAY:Date.UTC(2026,0,1);
 const to=valid.length?Math.max(...valid.map(s=>Math.max(dateStamp(s.planned_end_date),!paused&&Number.isFinite(dateStamp(s.projected_finish_date))?dateStamp(s.projected_finish_date):0)))+2*DAY:from+7*DAY;
 const days=Math.max(7,(to-from)/DAY);
 const width=Math.min(40000,Math.max(available,days*pixelsPerDay));
 return {from,to:from+days*DAY,days,width,pixelsPerDay:width/days};
}
export function dependencyCycle(graph:Record<string,string[]>){
 const done=new Set<string>();
 for(const root of Object.keys(graph)){if(done.has(root))continue;const active=new Set<string>();const stack:[string,boolean][]=[[root,false]];while(stack.length){const [node,leaving]=stack.pop()!;if(leaving){active.delete(node);done.add(node);continue;}if(active.has(node))return true;if(done.has(node))continue;active.add(node);stack.push([node,true]);for(const child of graph[node]??[])if(child in graph)stack.push([child,false]);}}
 return false;
}
export const safeCsvCell=(value:unknown)=>{let text=String(value??"");if(/^[=+@\-\t\r]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};
