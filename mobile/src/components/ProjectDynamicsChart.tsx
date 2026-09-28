import "./ProjectDynamicsChart.css";

export interface DynamicsPoint {
  date: string;
  percent: number;
}

interface Props {
  plan: DynamicsPoint[];
  fact: DynamicsPoint[];
  forecast: DynamicsPoint[];
  today: string;
}

const WIDTH = 1000;
const HEIGHT = 260;
const PADDING = { top: 16, right: 16, bottom: 30, left: 40 };

function timestamp(iso: string): number {
  return new Date(iso).getTime();
}

/**
 * Динамика проекта: план / факт / прогноз на одной оси времени (тот же подход, что и в
 * веб-версии). Честность источников: план — из длительностей этапов графика, факт —
 * визуальная оценка по снимкам, прогноз — линейная экстраполяция к расчётной дате сдачи.
 */
export function ProjectDynamicsChart({ plan, fact, forecast, today }: Props) {
  const allPoints = [...plan, ...fact, ...forecast];
  if (allPoints.length === 0) {
    return <p className="sk-empty-state">Недостаточно данных о графике, чтобы построить кривую.</p>;
  }

  const times = [...allPoints.map((p) => timestamp(p.date)), timestamp(today)];
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const span = Math.max(maxTime - minTime, 1);

  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;

  const x = (iso: string) => PADDING.left + ((timestamp(iso) - minTime) / span) * plotWidth;
  const y = (percent: number) => PADDING.top + (1 - Math.max(0, Math.min(100, percent)) / 100) * plotHeight;

  const line = (points: DynamicsPoint[]) => points.map((p) => `${x(p.date)},${y(p.percent)}`).join(" ");

  return (
    <div className="sk-dynamics-chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Динамика проекта: план, факт, прогноз">
        {[0, 25, 50, 75, 100].map((percent) => (
          <g key={percent}>
            <line
              className="sk-dynamics-chart__grid"
              x1={PADDING.left}
              x2={WIDTH - PADDING.right}
              y1={y(percent)}
              y2={y(percent)}
            />
            <text className="sk-dynamics-chart__axis" x={PADDING.left - 8} y={y(percent) + 4}>
              {percent}
            </text>
          </g>
        ))}

        {plan.length > 0 && <polyline className="sk-dynamics-chart__line sk-dynamics-chart__line--plan" points={line(plan)} />}

        {forecast.length > 0 && (
          <polyline className="sk-dynamics-chart__line sk-dynamics-chart__line--forecast" points={line(forecast)} />
        )}

        {fact.length > 0 && <polyline className="sk-dynamics-chart__line sk-dynamics-chart__line--fact" points={line(fact)} />}

        {timestamp(today) >= minTime && timestamp(today) <= maxTime && (
          <>
            <line
              className="sk-dynamics-chart__today"
              x1={x(today)}
              x2={x(today)}
              y1={PADDING.top}
              y2={PADDING.top + plotHeight}
            />
            <text className="sk-dynamics-chart__today-label" x={x(today) + 4} y={PADDING.top + 10}>
              сегодня
            </text>
          </>
        )}

        {fact.map((point) => (
          <circle key={point.date} className="sk-dynamics-chart__dot" cx={x(point.date)} cy={y(point.percent)} r={3.5}>
            <title>
              {new Date(point.date).toLocaleDateString("ru-RU")}: {point.percent}% (факт)
            </title>
          </circle>
        ))}

        <text className="sk-dynamics-chart__axis" x={PADDING.left} y={HEIGHT - 8}>
          {new Date(minTime).toLocaleDateString("ru-RU")}
        </text>
        <text className="sk-dynamics-chart__axis sk-dynamics-chart__axis--end" x={WIDTH - PADDING.right} y={HEIGHT - 8}>
          {new Date(maxTime).toLocaleDateString("ru-RU")}
        </text>
      </svg>

      <div className="sk-dynamics-chart__legend">
        <span className="sk-dynamics-chart__legend-item">
          <i className="sk-dynamics-chart__swatch sk-dynamics-chart__swatch--plan" /> План
        </span>
        <span className="sk-dynamics-chart__legend-item">
          <i className="sk-dynamics-chart__swatch sk-dynamics-chart__swatch--fact" /> Факт
        </span>
        <span className="sk-dynamics-chart__legend-item">
          <i className="sk-dynamics-chart__swatch sk-dynamics-chart__swatch--forecast" /> Прогноз
        </span>
      </div>
    </div>
  );
}
