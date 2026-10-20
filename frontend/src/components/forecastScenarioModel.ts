interface ScenarioWork {
  stage_id: string;
  planned_start_date: string;
  planned_end_date: string;
  predecessor_ids: string[];
  is_summary: boolean;
}
const DAY = 86400000;
/** Finish-to-start scenario in calendar days; never changes source observations. */
export function scenarioFinish(stages: ScenarioWork[], delays: Record<string, number>): string {
  const works = stages.filter(s => !s.is_summary);
  if (!works.length) throw Error('Нет работ для расчёта');
  const byId = new Map(works.map(s => [s.stage_id, s]));
  const finish = new Map<string, number>(), visiting = new Set<string>();
  const visit = (id: string): number => {
    if (finish.has(id)) return finish.get(id)!;
    const work = byId.get(id);
    if (!work || visiting.has(id)) throw Error('Проверьте зависимости работ');
    visiting.add(id);
    const start = Date.parse(work.planned_start_date);
    const duration = Math.round((Date.parse(work.planned_end_date) - start) / DAY) + 1;
    const delay = delays[id] ?? 0;
    if (!Number.isFinite(start) || !Number.isFinite(duration) || duration < 1 || !Number.isFinite(delay) || delay < 0) throw Error('Некорректные сроки');
    const earliest = Math.max(start, ...work.predecessor_ids.map(p => visit(p) + DAY));
    const value = earliest + (duration + delay - 1) * DAY;
    visiting.delete(id); finish.set(id, value); return value;
  };
  return new Date(Math.max(...works.map(s => visit(s.stage_id)))).toISOString().slice(0, 10);
}
