import {frameZoneColor} from "../frameZoneColors";
import {useEffect,useState} from "react";
import {Link} from "react-router-dom";
import {cameraReferenceImageUrl,fetchFrameZones,type FrameZonesResponse} from "../api";
import {useProject} from "../ProjectContext";
import {useAuth} from "../AuthContext";

export function CameraZonesCard({cameraId}:{cameraId:string}){
 const {projectId}=useProject();const {user}=useAuth();
 const [data,setData]=useState<FrameZonesResponse|null>(null),[error,setError]=useState(''),[imageError,setImageError]=useState(false),[size,setSize]=useState({width:1,height:1});
 useEffect(()=>{let active=true;setData(null);setError('');setImageError(false);fetchFrameZones(projectId,cameraId).then(value=>active&&setData(value)).catch(e=>active&&setError(e instanceof Error?e.message:'Не удалось загрузить зоны'));return()=>{active=false;};},[projectId,cameraId]);
 const url=`/projects/${projectId}/cameras/${cameraId}/zones`;
 return <section className="sk-zones-card"><header><div><h2>Зоны в кадре</h2><p>{data?.camera_name??'Загрузка зон…'}</p></div>{data&&<span className="sk-zones-card__count">{data.zones.length} зон</span>}</header>
 {error&&<p className="sk-panel--error">{error}</p>}
 <Link to={url} className="sk-zones-card__preview" aria-label="Открыть зоны выбранной камеры">
 {imageError?<div className="sk-zones-card__empty">Опорный кадр пока не загружен</div>:<><img src={cameraReferenceImageUrl(projectId,cameraId)} crossOrigin="use-credentials" alt="Предпросмотр зон камеры" onLoad={e=>setSize({width:e.currentTarget.naturalWidth,height:e.currentTarget.naturalHeight})} onError={()=>setImageError(true)}/><svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">{data?.zones.map((zone,index)=><polygon key={zone.id??index} points={zone.polygon.map(([x,y])=>`${x/(zone.reference_width??size.width)*1000},${y/(zone.reference_height??size.height)*1000}`).join(' ')} className="sk-zones-card__polygon" style={{stroke:frameZoneColor(zone),fill:frameZoneColor(zone)+"24"}}/>)}</svg></>}
 <span className="sk-zones-card__overlay">Открыть разметку →</span></Link>
 <div className="sk-zones-card__body">{data?.zones.length?<ul>{data.zones.map((zone,index)=><li key={zone.id??index}><span>{zone.name}</span><small>{zone.kind_label_ru??data.kinds.find(k=>k.key===zone.kind)?.label_ru??zone.kind}</small></li>)}</ul>:<p>{data?'Зоны ещё не размечены. Откройте редактор, чтобы добавить их.':'Загружаем разметку…'}</p>}</div>
 <footer><p>Просмотр и настройка рабочих участков, въездов и зон контроля.</p><Link className="sk-button" to={url}>{user?.role==='admin'?'Редактировать зоны':'Открыть зоны'} →</Link></footer>
 </section>;
}
