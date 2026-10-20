import type {DeviationDetailResponse} from '../api';
import {DecisionGraph} from './DecisionGraph';
import './DecisionTrace.css';

export function DecisionTrace({data}:{data:DeviationDetailResponse}) {


 return <section className="sk-trace" aria-labelledby="decision-trace-title">
  <header className="sk-trace-header"><div><span className="sk-trace-eyebrow">От наблюдения к решению</span><h2 id="decision-trace-title">Как сформирован вывод</h2><p>Раскройте этап, чтобы увидеть его данные, результат и влияние.</p></div></header>
  <div className="sk-trace-context"><strong>Данные отклонения</strong><span>{data.deviation.work_name||'Этап не указан'}</span><span>{data.deviation.zone_name}</span></div>
  <DecisionGraph data={data} demo={false}/><footer className="sk-trace-footer"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z"/><path d="m8 12 3 3 5-6"/></svg><span>Критичность задачи и доказанность обстоятельств оцениваются раздельно. Итог проверяется по снимкам и журналу решений ниже.</span></footer>
 </section>;
}

