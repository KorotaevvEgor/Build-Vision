import type { DelayBreakdown } from "../api";
import "./DelayFactorsDonut.css";

interface Props {
  breakdown: DelayBreakdown;
}

const CATEGORY_COLOR: Record<string, string> = {
  missing_equipment: "var(--sk-status-danger)",
  weather: "var(--sk-accent)",
  schedule_deviation: "var(--sk-status-warning)",
};

function categoryColor(key: string): string {
  return CATEGORY_COLOR[key] ?? "var(--sk-text-faint)";
}

const SIZE = 160;
const STROKE = 20;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * Донат влияния факторов на прогноз: кольцо из дуг по категориям (SVG stroke-dasharray,
 * без библиотек графиков — тот же подход, что и у остальных графиков в проекте), с
 * текущим сдвигом срока сдачи крупно по центру и расшифровкой справа.
 */
export function DelayFactorsDonut({ breakdown }: Props) {
  const centerLabel =
    breakdown.shift_days > 0 ? `+${breakdown.shift_days}` : breakdown.shift_days < 0 ? `${breakdown.shift_days}` : "0";
  const centerSub = breakdown.shift_days > 0 ? "дней задержки" : breakdown.shift_days < 0 ? "дней с опережением" : "в графике";

  let cursor = 0;

  return (
    <div className="sk-delay-donut">
      <div className="sk-delay-donut__chart">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Влияние факторов на прогноз">
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="var(--sk-surface-muted)"
            strokeWidth={STROKE}
          />
          {breakdown.categories.map((category) => {
            const length = (category.share_percent / 100) * CIRCUMFERENCE;
            const dashArray = `${length} ${CIRCUMFERENCE - length}`;
            const offset = -cursor;
            cursor += length;
            return (
              <circle
                key={category.key}
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={RADIUS}
                fill="none"
                stroke={categoryColor(category.key)}
                strokeWidth={STROKE}
                strokeDasharray={dashArray}
                strokeDashoffset={offset}
                transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
                strokeLinecap="butt"
              >
                <title>
                  {category.label_ru}: {category.days} дн. ({category.share_percent}%)
                </title>
              </circle>
            );
          })}
        </svg>
        <div className="sk-delay-donut__center">
          <strong>{centerLabel}</strong>
          <span>{centerSub}</span>
        </div>
      </div>

      <ul className="sk-delay-donut__legend">
        {breakdown.categories.map((category) => (
          <li key={category.key} className="sk-delay-donut__legend-item">
            <i className="sk-delay-donut__dot" style={{ background: categoryColor(category.key) }} />
            <span className="sk-delay-donut__legend-label">{category.label_ru}</span>
            <span className="sk-delay-donut__legend-value">
              {category.days} дн. · {category.share_percent}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
