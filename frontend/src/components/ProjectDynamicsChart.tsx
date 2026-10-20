import { useState, type MouseEvent } from "react";
import "./ProjectDynamicsChart.css";

export interface DynamicsPoint {
  date: string;
  percent: number;
}

/** Плановый период работы — для ленты этапов под графиком. */
export interface DynamicsStage {
  name: string;
  start: string;
  end: string;
}

interface Props {
  plan: DynamicsPoint[];
  fact: DynamicsPoint[];
  forecast: DynamicsPoint[];
  today: string;
  stages?: DynamicsStage[];
  baselineFinish?: string | null;
  projectedFinish?: string | null;
  showDeadlineSummary?: boolean;
}

const WIDTH = 1000;
const HEIGHT = 350;
const PADDING = { top: 34, right: 26, bottom: 66, left: 46 };
const DAY = 86_400_000;
const SHORT_MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

function ts(iso: string): number {
  return new Date(iso).getTime();
}

function formatDate(t: number | string): string {
  const d = typeof t === "string" ? new Date(t) : new Date(t);
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function isoDay(t: number): string {
  return new Date(t).toISOString().slice(0, 10);
}

/** Линейная интерполяция по точкам; вне диапазона точек значения нет (а не «замороженный» край). */
function valueAt(points: DynamicsPoint[], t: number): number | null {
  if (points.length === 0) return null;
  const first = ts(points[0].date);
  const last = ts(points[points.length - 1].date);
  if (t < first || t > last) return null;
  for (let i = 0; i < points.length - 1; i++) {
    const ta = ts(points[i].date);
    const tb = ts(points[i + 1].date);
    if (t >= ta && t <= tb) {
      if (tb <= ta) return points[i + 1].percent;
      return points[i].percent + (points[i + 1].percent - points[i].percent) * ((t - ta) / (tb - ta));
    }
  }
  return points[points.length - 1].percent;
}

function plural(days: number): string {
  const n = Math.abs(days) % 100;
  const last = n % 10;
  if (n > 10 && n < 20) return "дней";
  if (last === 1) return "день";
  if (last >= 2 && last <= 4) return "дня";
  return "дней";
}

interface Hover {
  t: number;
  /** Позиция курсора в долях ширины графика — для позиционирования подсказки. */
  xFraction: number;
}

/**
 * Динамика проекта: план / факт / прогноз на одной оси времени. Рисуется вручную на SVG (без сторонней
 * библиотеки). Все три линии стартуют из одной общей точки — начала проекта (0%), чтобы их можно было
 * сравнивать «от одного нуля». Честность источников (см. SchedulePage.tsx): план — из длительностей этапов
 * графика, факт — визуальная оценка готовности по снимкам (участок от старта до первого замера — только
 * пунктирная связка, замеров там нет), прогноз — линейная экстраполяция от последнего замера к расчётной
 * дате сдачи.
 */
export function ProjectDynamicsChart({
  plan,
  fact,
  forecast,
  today,
  stages = [],
  baselineFinish = null,
  projectedFinish = null,
  showDeadlineSummary = true,
}: Props) {
  const [hover, setHover] = useState<Hover | null>(null);

  const allPoints = [...plan, ...fact, ...forecast];
  if (allPoints.length === 0) {
    return <p className="sk-empty-state">Недостаточно данных о графике, чтобы построить кривую.</p>;
  }

  const times = [...allPoints.map((p) => ts(p.date)), ts(today)];
  if (baselineFinish) times.push(ts(baselineFinish));
  if (projectedFinish) times.push(ts(projectedFinish));
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const span = Math.max(maxTime - minTime, 1);
  const todayTime = ts(today);

  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;
  const plotBottom = PADDING.top + plotHeight;

  const xT = (t: number) => PADDING.left + ((t - minTime) / span) * plotWidth;
  const x = (iso: string) => xT(ts(iso));
  const y = (percent: number) => PADDING.top + (1 - Math.max(0, Math.min(100, percent)) / 100) * plotHeight;

  const polyline = (points: DynamicsPoint[]) => points.map((p) => `${x(p.date)},${y(p.percent)}`).join(" ");
  const areaPath = (points: DynamicsPoint[]) => {
    if (points.length === 0) return "";
    const body = points.map((p) => `L${x(p.date)},${y(p.percent)}`).join(" ");
    const first = points[0];
    const last = points[points.length - 1];
    return `M${x(first.date)},${plotBottom} ${body} L${x(last.date)},${plotBottom} Z`;
  };

  // Общая точка старта: и факт, и прогноз, и план начинаются от начала проекта.
  const originIso = isoDay(minTime);
  const factSeries: DynamicsPoint[] =
    fact.length > 0 ? (ts(fact[0].date) > minTime ? [{ date: originIso, percent: 0 }, ...fact] : fact) : [];
  const leadIn = factSeries.length > 1 && fact.length > 0 && factSeries[0] !== fact[0] ? factSeries.slice(0, 2) : null;
  const lastFact = fact.length > 0 ? fact[fact.length - 1] : null;

  // Подписи оси X по месяцам: шаг подбирается по длине горизонта, чтобы подписи не слипались.
  const startMonth = new Date(minTime);
  const totalMonths =
    (new Date(maxTime).getFullYear() - startMonth.getFullYear()) * 12 +
    (new Date(maxTime).getMonth() - startMonth.getMonth()) +
    1;
  const labelStep = totalMonths <= 8 ? 1 : totalMonths <= 16 ? 2 : totalMonths <= 27 ? 3 : 6;
  const monthTicks: { t: number; label: string; major: boolean }[] = [];
  {
    let cursor = new Date(startMonth.getFullYear(), startMonth.getMonth() + 1, 1);
    let index = 0;
    while (cursor.getTime() <= maxTime) {
      const major = index % labelStep === 0;
      monthTicks.push({
        t: cursor.getTime(),
        label: `${SHORT_MONTHS[cursor.getMonth()]} ${String(cursor.getFullYear()).slice(2)}`,
        major,
      });
      cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
      index += 1;
    }
  }

  const planToday = valueAt(plan, todayTime);
  const planAtFact = lastFact ? valueAt(plan, ts(lastFact.date)) : null;
  const gap = lastFact && planAtFact !== null ? Math.round(lastFact.percent - planAtFact) : null;
  const shiftDays =
    baselineFinish && projectedFinish ? Math.round((ts(projectedFinish) - ts(baselineFinish)) / DAY) : null;
  const finishTime = projectedFinish ? ts(projectedFinish) : baselineFinish ? ts(baselineFinish) : null;

  const onMove = (event: MouseEvent<SVGRectElement>) => {
    const rect = event.currentTarget.ownerSVGElement?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    const viewX = ((event.clientX - rect.left) / rect.width) * WIDTH;
    const fraction = Math.max(0, Math.min(1, (viewX - PADDING.left) / plotWidth));
    setHover({ t: minTime + fraction * span, xFraction: (viewX / WIDTH) });
  };

  const hoverPlan = hover ? valueAt(plan, hover.t) : null;
  const hoverForecast = hover ? valueAt(forecast, hover.t) : null;
  const hoverFact =
    hover && fact.length > 0
      ? fact.reduce<DynamicsPoint | null>((best, point) => {
          const distance = Math.abs(ts(point.date) - hover.t);
          if (distance > 10 * DAY) return best;
          return best === null || distance < Math.abs(ts(best.date) - hover.t) ? point : best;
        }, null)
      : null;

  return (
    <div className="sk-dynamics-chart">
      <div className="sk-dynamics-chart__kpis">
        <div className="sk-dynamics-chart__kpi sk-dynamics-chart__kpi--plan">
          <span className="sk-dynamics-chart__kpi-label">План на сегодня</span>
          <strong>{planToday !== null ? `${Math.round(planToday)}%` : "—"}</strong>
          <span className="sk-dynamics-chart__kpi-foot">по длительности этапов</span>
        </div>
        <div className="sk-dynamics-chart__kpi sk-dynamics-chart__kpi--fact">
          <span className="sk-dynamics-chart__kpi-label">Фотооценка готовности</span>
          <strong>{lastFact ? `${Math.round(lastFact.percent)}%` : "—"}</strong>
          <span className="sk-dynamics-chart__kpi-foot">
            {lastFact ? `замер от ${formatDate(lastFact.date)}` : "подтверждённых замеров нет"}
          </span>
        </div>
        <div
          className={`sk-dynamics-chart__kpi ${
            gap === null ? "" : gap < 0 ? "sk-dynamics-chart__kpi--bad" : "sk-dynamics-chart__kpi--good"
          }`}
        >
          <span className="sk-dynamics-chart__kpi-label">Фотооценка к плану</span>
          <strong>{gap !== null ? `${gap > 0 ? "+" : gap < 0 ? "−" : ""}${Math.abs(gap)} п.п.` : "—"}</strong>
          <span className="sk-dynamics-chart__kpi-foot">на дату последнего замера</span>
        </div>
        {showDeadlineSummary&&<div
          className={`sk-dynamics-chart__kpi ${
            shiftDays === null ? "" : shiftDays > 0 ? "sk-dynamics-chart__kpi--bad" : "sk-dynamics-chart__kpi--good"
          }`}
        >
          <span className="sk-dynamics-chart__kpi-label">Сдача объекта</span>
          <strong>
            {shiftDays === null
              ? "—"
              : shiftDays === 0
                ? "в срок"
                : `${shiftDays > 0 ? "+" : "−"}${Math.abs(shiftDays)} ${plural(shiftDays)}`}
          </strong>
          <span className="sk-dynamics-chart__kpi-foot">
            {projectedFinish ? `сценарий ${formatDate(projectedFinish)}` : "прогноз недоступен"}
          </span>
        </div>}
      </div>

      <div className="sk-dynamics-chart__canvas">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Динамика проекта: план, факт, прогноз">
          <defs>
            <linearGradient id="sk-dyn-plan-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" style={{ stopColor: "var(--sk-text-muted)", stopOpacity: 0.22 }} />
              <stop offset="100%" style={{ stopColor: "var(--sk-text-muted)", stopOpacity: 0 }} />
            </linearGradient>
            <linearGradient id="sk-dyn-fact-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" style={{ stopColor: "var(--sk-status-ok)", stopOpacity: 0.42 }} />
              <stop offset="100%" style={{ stopColor: "var(--sk-status-ok)", stopOpacity: 0.02 }} />
            </linearGradient>
          </defs>

          {/* Вертикальная сетка по месяцам */}
          {monthTicks.map((tick) => (
            <g key={tick.t}>
              <line
                className={`sk-dynamics-chart__vgrid${tick.major ? " sk-dynamics-chart__vgrid--major" : ""}`}
                x1={xT(tick.t)}
                x2={xT(tick.t)}
                y1={PADDING.top}
                y2={plotBottom}
              />
              {tick.major && (
                <text className="sk-dynamics-chart__axis sk-dynamics-chart__axis--x" x={xT(tick.t)} y={plotBottom + 16}>
                  {tick.label}
                </text>
              )}
            </g>
          ))}

          {/* Горизонтальная сетка и ось Y */}
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
                {percent}%
              </text>
            </g>
          ))}

          {/* План: заливка + линия */}
          {plan.length > 0 && (
            <>
              <path d={areaPath(plan)} fill="url(#sk-dyn-plan-grad)" />
              <polyline className="sk-dynamics-chart__line sk-dynamics-chart__line--plan" points={polyline(plan)} />
            </>
          )}

          {/* Факт: заливка, связка от старта проекта до первого замера, реальные замеры */}
          {factSeries.length > 0 && <path d={areaPath(factSeries)} fill="url(#sk-dyn-fact-grad)" />}
          {leadIn && (
            <polyline className="sk-dynamics-chart__line sk-dynamics-chart__line--lead" points={polyline(leadIn)} />
          )}
          {fact.length > 1 && (
            <polyline className="sk-dynamics-chart__line sk-dynamics-chart__line--fact" points={polyline(fact)} />
          )}

          {/* Прогноз от последнего замера до 100% */}
          {forecast.length > 0 && (
            <polyline
              className="sk-dynamics-chart__line sk-dynamics-chart__line--forecast"
              points={polyline(forecast)}
            />
          )}

          {/* Общая точка старта всех линий */}
          <circle className="sk-dynamics-chart__origin" cx={xT(minTime)} cy={y(0)} r={4.5}>
            <title>Старт проекта, {formatDate(minTime)} — общая точка отсчёта для плана, факта и прогноза</title>
          </circle>

          {/* Сегодня */}
          {todayTime >= minTime && todayTime <= maxTime && (
            <>
              <line
                className="sk-dynamics-chart__today"
                x1={xT(todayTime)}
                x2={xT(todayTime)}
                y1={PADDING.top - 4}
                y2={plotBottom}
              />
              <rect
                className="sk-dynamics-chart__today-pill"
                x={xT(todayTime) - 34}
                y={PADDING.top - 24}
                width={68}
                height={17}
                rx={8.5}
              />
              <text className="sk-dynamics-chart__today-label" x={xT(todayTime)} y={PADDING.top - 12}>
                Сегодня
              </text>
            </>
          )}

          {/* Конец плана и прогнозная сдача */}
          {finishTime !== null && (
            <>
              <circle className="sk-dynamics-chart__end" cx={xT(finishTime)} cy={y(100)} r={5}>
                <title>
                  {baselineFinish ? `План: ${formatDate(baselineFinish)}` : ""}
                  {projectedFinish ? ` · Сценарий: ${formatDate(projectedFinish)}` : ""}
                </title>
              </circle>
              <text className="sk-dynamics-chart__end-label" x={xT(finishTime) - 10} y={y(100) + 18}>
                {projectedFinish ? `Сдача ${formatDate(projectedFinish)}` : `План ${formatDate(finishTime)}`}
              </text>
            </>
          )}

          {/* Реальные замеры факта */}
          {fact.map((point, index) => {
            const isLast = index === fact.length - 1;
            return (
              <g key={point.date}>
                {isLast && (
                  <circle className="sk-dynamics-chart__dot-halo" cx={x(point.date)} cy={y(point.percent)} r={9} />
                )}
                <circle className="sk-dynamics-chart__dot" cx={x(point.date)} cy={y(point.percent)} r={4.5}>
                  <title>
                    {formatDate(point.date)}: {point.percent}% (факт)
                  </title>
                </circle>
                {isLast && (
                  <text
                    className="sk-dynamics-chart__dot-label"
                    x={x(point.date) - 12}
                    y={y(point.percent) - 12}
                  >
                    {Math.round(point.percent)}%
                  </text>
                )}
              </g>
            );
          })}

          {/* Лента этапов под графиком */}
          <text className="sk-dynamics-chart__axis" x={PADDING.left - 8} y={plotBottom + 41}>
            Этапы
          </text>
          {stages.map((stage, index) => {
            const x0 = xT(ts(stage.start));
            const x1 = xT(ts(stage.end) + DAY);
            const width = Math.max(x1 - x0, 1);
            const isCurrent = todayTime >= ts(stage.start) && todayTime <= ts(stage.end) + DAY - 1;
            const maxChars = Math.floor((width - 8) / 6.4);
            const label = maxChars >= 4 ? (stage.name.length > maxChars ? `${stage.name.slice(0, maxChars - 1)}…` : stage.name) : "";
            return (
              <g key={`${stage.name}-${index}`}>
                <rect
                  className={`sk-dynamics-chart__stage${isCurrent ? " sk-dynamics-chart__stage--current" : ""}${
                    index % 2 === 1 ? " sk-dynamics-chart__stage--alt" : ""
                  }`}
                  x={x0 + 0.5}
                  y={plotBottom + 30}
                  width={Math.max(width - 1, 1)}
                  height={16}
                  rx={3}
                >
                  <title>
                    {stage.name}: {formatDate(stage.start)} – {formatDate(stage.end)}
                  </title>
                </rect>
                {label && (
                  <text className="sk-dynamics-chart__stage-label" x={x0 + 5} y={plotBottom + 42}>
                    {label}
                  </text>
                )}
              </g>
            );
          })}

          {/* Наведение: курсор и перекрестие */}
          {hover && (
            <line
              className="sk-dynamics-chart__crosshair"
              x1={xT(hover.t)}
              x2={xT(hover.t)}
              y1={PADDING.top}
              y2={plotBottom}
            />
          )}
          <rect
            className="sk-dynamics-chart__hit"
            x={PADDING.left}
            y={PADDING.top}
            width={plotWidth}
            height={plotHeight}
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          />
        </svg>

        {hover && (
          <div
            className="sk-dynamics-chart__tooltip"
            style={{
              left: `${hover.xFraction * 100}%`,
              transform: hover.xFraction > 0.62 ? "translateX(calc(-100% - 14px))" : "translateX(14px)",
            }}
          >
            <div className="sk-dynamics-chart__tooltip-date">{formatDate(hover.t)}</div>
            <div className="sk-dynamics-chart__tooltip-row">
              <i className="sk-dynamics-chart__swatch sk-dynamics-chart__swatch--plan" />
              План: <b>{hoverPlan !== null ? `${Math.round(hoverPlan)}%` : "—"}</b>
            </div>
            {hoverFact && (
              <div className="sk-dynamics-chart__tooltip-row">
                <i className="sk-dynamics-chart__swatch sk-dynamics-chart__swatch--fact" />
                Факт: <b>{Math.round(hoverFact.percent)}%</b>
                <span className="sk-dynamics-chart__tooltip-muted"> замер {formatDate(hoverFact.date)}</span>
              </div>
            )}
            {hoverForecast !== null && (
              <div className="sk-dynamics-chart__tooltip-row">
                <i className="sk-dynamics-chart__swatch sk-dynamics-chart__swatch--forecast" />
                Сценарий: <b>{Math.round(hoverForecast)}%</b>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="sk-dynamics-chart__legend">
        <span className="sk-dynamics-chart__legend-item">
          <i className="sk-dynamics-chart__swatch sk-dynamics-chart__swatch--plan" /> План (по длительности этапов)
        </span>
        <span className="sk-dynamics-chart__legend-item">
          <i className="sk-dynamics-chart__swatch sk-dynamics-chart__swatch--fact" /> Фотооценка готовности
        </span>
        <span className="sk-dynamics-chart__legend-item">
          <i className="sk-dynamics-chart__swatch sk-dynamics-chart__swatch--lead" /> Замеров до первого снимка нет
        </span>
        <span className="sk-dynamics-chart__legend-item">
          <i className="sk-dynamics-chart__swatch sk-dynamics-chart__swatch--forecast" /> Сценарий по подтверждённым объёмам
        </span>
      </div>
    </div>
  );
}
