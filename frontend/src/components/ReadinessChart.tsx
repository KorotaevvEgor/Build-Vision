import type { PlannedStageBand, ReadinessPoint } from "../api";
import "./ReadinessChart.css";

interface Props {
  fact: ReadinessPoint[];
  plannedStages: PlannedStageBand[];
  today: string;
}

const WIDTH = 900;
const HEIGHT = 260;
const PADDING = { top: 16, right: 16, bottom: 34, left: 40 };

function timestamp(iso: string): number {
  return new Date(iso).getTime();
}

/**
 * Готовность объекта во времени. Рисуется вручную на SVG, а не библиотекой:
 * график один, ему нужны полосы этапов на фоне и вертикаль «сегодня», и это
 * дешевле нарисовать, чем тянуть зависимость и подгонять её под тему.
 */
export function ReadinessChart({ fact, plannedStages, today }: Props) {
  if (fact.length === 0) {
    return (
      <p className="sk-empty-state">
        Нет снимков с подтверждённой датой и оценкой готовности — строить нечего.
      </p>
    );
  }

  const times = [
    ...fact.map((point) => timestamp(point.date)),
    ...plannedStages.flatMap((band) => [timestamp(band.start_date), timestamp(band.end_date)]),
    timestamp(today),
  ];
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const span = Math.max(maxTime - minTime, 1);

  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;

  const x = (iso: string) => PADDING.left + ((timestamp(iso) - minTime) / span) * plotWidth;
  const y = (percent: number) => PADDING.top + (1 - percent / 100) * plotHeight;

  const line = fact.map((point) => `${x(point.date)},${y(point.readiness_percent)}`).join(" ");

  return (
    <div className="sk-readiness-chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Готовность объекта во времени">
        {[0, 25, 50, 75, 100].map((percent) => (
          <g key={percent}>
            <line
              className="sk-readiness-chart__grid"
              x1={PADDING.left}
              x2={WIDTH - PADDING.right}
              y1={y(percent)}
              y2={y(percent)}
            />
            <text className="sk-readiness-chart__axis" x={PADDING.left - 8} y={y(percent) + 4}>
              {percent}
            </text>
          </g>
        ))}

        {plannedStages.map((band, index) => {
          const left = x(band.start_date);
          const width = Math.max(x(band.end_date) - left, 2);
          return (
            <g key={band.stage_id}>
              <rect
                className={`sk-readiness-chart__band${
                  band.is_current ? " sk-readiness-chart__band--current" : ""
                }`}
                x={left}
                y={PADDING.top}
                width={width}
                height={plotHeight}
              />
              <text
                className="sk-readiness-chart__band-label"
                x={left + 4}
                y={PADDING.top + 14 + (index % 2) * 14}
              >
                {band.work_name}
              </text>
            </g>
          );
        })}

        <line
          className="sk-readiness-chart__today"
          x1={x(today)}
          x2={x(today)}
          y1={PADDING.top}
          y2={PADDING.top + plotHeight}
        />
        <text className="sk-readiness-chart__today-label" x={x(today) - 4} y={PADDING.top + 10}>
          сегодня
        </text>

        <polyline className="sk-readiness-chart__line" points={line} />
        {fact.map((point) => (
          <g key={point.date}>
            <circle
              className="sk-readiness-chart__dot"
              cx={x(point.date)}
              cy={y(point.readiness_percent)}
              r={4}
            >
              <title>
                {new Date(point.date).toLocaleDateString("ru-RU")}: {point.readiness_percent}%
                {point.frames > 1 ? ` (по ${point.frames} ракурсам, разброс ${point.spread}%)` : ""}
                {point.stage_label ? ` — ${point.stage_label}` : ""}
              </title>
            </circle>
          </g>
        ))}

        <text className="sk-readiness-chart__axis" x={PADDING.left} y={HEIGHT - 10}>
          {new Date(fact[0].date).toLocaleDateString("ru-RU")}
        </text>
        <text
          className="sk-readiness-chart__axis sk-readiness-chart__axis--end"
          x={WIDTH - PADDING.right}
          y={HEIGHT - 10}
        >
          {new Date(today).toLocaleDateString("ru-RU")}
        </text>
      </svg>
    </div>
  );
}
