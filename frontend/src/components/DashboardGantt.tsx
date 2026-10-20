import type { NetworkStage } from "../api";

const day = 86400000;
const stamp = (date: string) => Date.parse(`${date}T00:00:00Z`);
const label = (time: number) => new Date(time).toLocaleDateString("ru-RU", { day: "2-digit", month: "short", year: "2-digit", timeZone: "UTC" });

export function DashboardGantt({ stages, currentStageId, paused }: { stages: NetworkStage[]; currentStageId?: string; paused: boolean }) {
  const ordered = stages.filter(s => !s.is_summary && Number.isFinite(stamp(s.planned_start_date)) && Number.isFinite(stamp(s.planned_end_date))).sort((a,b) => a.planned_start_date.localeCompare(b.planned_start_date));
  if (!ordered.length) return <p className="sk-empty-state">В плане пока нет этапов с датами.</p>;
  const index = Math.max(0, ordered.findIndex(s => s.stage_id === currentStageId));
  const start = Math.min(Math.max(0, index - 2), Math.max(0, ordered.length - 5));
  const visible = ordered.slice(start, start + 5);
  const from = Math.min(...visible.map(s => stamp(s.planned_start_date)));
  const to = Math.max(...visible.map(s => stamp(s.planned_end_date))) + day;
  const span = Math.max(day, to - from);
  return <>
    <p className="sk-dashboard-gantt__subtitle">Плановые сроки · {visible.length} из {ordered.length} этапов{paused ? " · Проект приостановлен" : ""}</p>
    <div className="sk-dashboard-gantt" role="region" aria-label="Фрагмент календарного плана Ганта">
      <div className="sk-dashboard-gantt__axis"><span>Этап</span><div>{[0,.5,1].map(f => <span key={f}>{label(from + (span - day) * f)}</span>)}</div></div>
      {visible.map(s => <div key={s.stage_id} className={`sk-dashboard-gantt__row${s.stage_id === currentStageId ? " sk-dashboard-gantt__row--current" : ""}`} title={`${s.work_name}: ${s.planned_start_date} — ${s.planned_end_date}`}>
        <span className="sk-dashboard-gantt__name">{s.work_name}</span>
        <div className="sk-dashboard-gantt__track"><span className={`sk-dashboard-gantt__bar${paused ? " sk-dashboard-gantt__bar--paused" : ""}`} style={{left:`${(stamp(s.planned_start_date)-from)/span*100}%`,width:`${Math.max(.7,(stamp(s.planned_end_date)+day-stamp(s.planned_start_date))/span*100)}%`}} /></div>
      </div>)}
    </div>
    <div className="sk-dashboard-gantt__legend"><i />{paused ? "Последний этап выделен · График приостановлен" : "Текущий этап выделен"}</div>
  </>;
}
