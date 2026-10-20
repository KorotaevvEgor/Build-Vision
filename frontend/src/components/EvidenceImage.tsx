import {evidenceBoxes,type EvidenceDetection} from "./evidenceImageModel";
import "./EvidenceImage.css";
interface Props {src:string;fullSizeUrl:string;alt:string;width:number|null;height:number|null;detections:EvidenceDetection[]}
export function EvidenceImage({src,fullSizeUrl,alt,width,height,detections}:Props){
 const boxes=evidenceBoxes(detections,width,height);
 return <><a className="sk-evidence-image" href={fullSizeUrl} target="_blank" rel="noreferrer" aria-label={`${alt}. Открыть снимок в полном размере`}>
  <img src={src} alt={alt} crossOrigin="use-credentials" loading="lazy"/>
  <span className="sk-evidence-overlay" aria-hidden="true">{boxes.map((box,index)=><span key={`${box.detection.id}-${index}`} className={`sk-evidence-box${box.detection.ambiguous?' sk-evidence-box--ambiguous':''}`} style={{left:`${box.left}%`,top:`${box.top}%`,width:`${box.width}%`,height:`${box.height}%`}}><span>{index+1}. {box.detection.label_ru||box.detection.class_key}</span></span>)}</span>
 </a><div className="sk-evidence-detection-list">{boxes.length?<><p>Сохранённые детекции снимка. Рамки не означают, что техника засчитана работе в исторической проверке.</p><ol>{boxes.map(({detection:d},index)=><li key={`${d.id}-${index}`}><strong>{d.label_ru||d.class_key}</strong>{Number.isFinite(d.confidence)?` · уверенность ${Math.round(Math.max(0,Math.min(1,d.confidence))*100)}%`:''}{d.ambiguous?' · неоднозначный класс':''}{d.activity_reason?` · ${d.activity_reason}`:''}</li>)}</ol></>:<p>{detections.length?'Рамки недоступны: нет размеров исходного снимка или корректных координат.':'Для снимка нет сохранённых рамок детектора.'}</p>}</div></>;
}
