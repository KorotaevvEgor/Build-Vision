interface CriticalWork {is_critical:boolean;early_start_date:string;early_finish_date:string;}
/** A critical FS edge is tight in the early-date schedule, not just two critical nodes. */
export function criticalEdge(from:CriticalWork|undefined,to:CriticalWork|undefined){
 if(!from?.is_critical||!to?.is_critical)return false;
 const gap=(Date.parse(to.early_start_date)-Date.parse(from.early_finish_date))/86400000;
 return gap===1;
}
