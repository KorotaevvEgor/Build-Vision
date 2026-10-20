export interface EvidenceDetection {id:number;class_key:string;label_ru:string;confidence:number;bbox:number[];ambiguous:boolean;activity:string;activity_reason:string}
export function evidenceBoxes(detections:EvidenceDetection[],width:number|null,height:number|null){
 if(!width||!height||!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)return [];
 return detections.flatMap(d=>{
  if(!Array.isArray(d.bbox)||d.bbox.length!==4||!d.bbox.every(v=>typeof v==='number'&&Number.isFinite(v)))return [];
  const [a,b,c,e]=d.bbox;
  const x1=Math.max(0,Math.min(width,a)),y1=Math.max(0,Math.min(height,b));
  const x2=Math.max(0,Math.min(width,c)),y2=Math.max(0,Math.min(height,e));
  if(x2<=x1||y2<=y1)return [];
  return [{detection:d,left:x1/width*100,top:y1/height*100,width:(x2-x1)/width*100,height:(y2-y1)/height*100}];
 });
}
