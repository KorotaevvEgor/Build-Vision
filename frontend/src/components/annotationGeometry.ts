export type AnnotationBox=[number,number,number,number];
export type BoxHandle='n'|'ne'|'e'|'se'|'s'|'sw'|'w'|'nw'|'move';
const clamp=(n:number,min:number,max:number)=>Math.min(max,Math.max(min,n));
export function adjustAnnotationBox(box:AnnotationBox,handle:BoxHandle,dx:number,dy:number,width:number,height:number):AnnotationBox {
 let [x1,y1,x2,y2]=box;
 if(handle==='move'){
  const x=clamp(Math.round(dx),-x1,width-x2),y=clamp(Math.round(dy),-y1,height-y2);
  return [x1+x,y1+y,x2+x,y2+y];
 }
 if(handle.includes('w'))x1=clamp(Math.round(x1+dx),0,x2-1);
 if(handle.includes('e'))x2=clamp(Math.round(x2+dx),x1+1,width);
 if(handle.includes('n'))y1=clamp(Math.round(y1+dy),0,y2-1);
 if(handle.includes('s'))y2=clamp(Math.round(y2+dy),y1+1,height);
 return [x1,y1,x2,y2];
}
export function boxHandles([x1,y1,x2,y2]:AnnotationBox):{key:BoxHandle;x:number;y:number;cursor:string;label:string}[]{
 const cx=(x1+x2)/2,cy=(y1+y2)/2;
 return [{key:'nw',x:x1,y:y1,cursor:'nwse-resize',label:'Верхний левый угол'},{key:'n',x:cx,y:y1,cursor:'ns-resize',label:'Верхняя сторона'},{key:'ne',x:x2,y:y1,cursor:'nesw-resize',label:'Верхний правый угол'},
 {key:'e',x:x2,y:cy,cursor:'ew-resize',label:'Правая сторона'},{key:'se',x:x2,y:y2,cursor:'nwse-resize',label:'Нижний правый угол'},{key:'s',x:cx,y:y2,cursor:'ns-resize',label:'Нижняя сторона'},{key:'sw',x:x1,y:y2,cursor:'nesw-resize',label:'Нижний левый угол'},{key:'w',x:x1,y:cy,cursor:'ew-resize',label:'Левая сторона'}];
}
