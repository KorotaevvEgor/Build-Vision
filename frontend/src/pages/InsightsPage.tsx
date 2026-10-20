import {lazy,Suspense} from "react";
import {useSearchParams} from "react-router-dom";
import {useProject} from "../ProjectContext";
import "./InsightsPage.css";
const Forecast=lazy(()=>import("./ForecastPage").then(m=>({default:m.ForecastPage})));
const Analytics=lazy(()=>import("./AnalyticsPage").then(m=>({default:m.AnalyticsPage})));
export function InsightsPage(){
 const [params,setParams]=useSearchParams();const facts=params.get("tab")==="observations";const {project}=useProject();
 return <div className="sk-insights"><header className="sk-insights-heading"><div><span className="sk-insights-eyebrow">Контроль строительства</span><h1>Прогноз и аналитика</h1><p>{project.name} · {facts?"Наблюдения, техника и история отклонений":"Сроки, динамика и причины возможного сдвига"}</p></div><button className="sk-button" onClick={()=>window.print()}>Печать отчёта</button></header>
 <div className="sk-insights-tabs" role="tablist" aria-label="Раздел анализа"><button role="tab" id="insights-forecast-tab" aria-controls="insights-panel" aria-selected={!facts} onClick={()=>setParams({})}>Прогноз сроков</button><button role="tab" id="insights-facts-tab" aria-controls="insights-panel" aria-selected={facts} onClick={()=>setParams({tab:"observations"})}>Аналитика наблюдений</button></div>
 <div id="insights-panel" role="tabpanel" aria-labelledby={facts?"insights-facts-tab":"insights-forecast-tab"}><Suspense fallback={<div className="sk-panel" role="status">Загрузка данных анализа…</div>}>{facts?<Analytics embedded/>:<Forecast embedded/>}</Suspense></div></div>;
}
