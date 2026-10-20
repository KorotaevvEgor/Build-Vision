/** Duration-weighted plan at chronological boundaries, including parallel work. */
export function projectPlanCurve(stages:{planned_start_date:string;planned_end_date:string}[]){
 const day=86400000;
 const ranges=stages.map(s=>({start:Date.parse(s.planned_start_date+"T00:00:00Z"),end:Date.parse(s.planned_end_date+"T00:00:00Z")})).filter(s=>Number.isFinite(s.start)&&Number.isFinite(s.end)&&s.end>=s.start);
 if(!ranges.length)return [];
 const total=ranges.reduce((sum,s)=>sum+(s.end-s.start)/day+1,0);
 const dates=[...new Set([Math.min(...ranges.map(s=>s.start))-day,...ranges.flatMap(s=>[s.start-day,s.start,s.end])])].sort((a,b)=>a-b);
 return dates.map(date=>({date:new Date(date).toISOString().slice(0,10),percent:Math.round(ranges.reduce((sum,s)=>sum+Math.max(0,Math.min((s.end-s.start)/day+1,(date-s.start)/day+1)),0)/total*1000)/10}));
}
