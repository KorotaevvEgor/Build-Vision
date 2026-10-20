import {criticalEdge} from "./criticalPath";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { NetworkStage } from "../api";
import { durationDays, formatPlanDate } from "./scheduleV2Model";
import { networkLayout, NODE_HEIGHT, NODE_WIDTH } from "./scheduleNetworkLayout";
import "./ScheduleNetworkView.css";

interface Props {
  showCritical?: boolean;
  stages: NetworkStage[];
  paused: boolean;
  currentId?: string;
  selected: string | null;
  onSelect: (id: string) => void;
  onOpen: (id: string) => void;
}

export function ScheduleNetworkView({ showCritical=true, stages, paused, currentId, selected, onSelect, onOpen }: Props) {
  const layout = useMemo(() => networkLayout(stages), [stages]);
  const viewport = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [viewportWidth, setViewportWidth] = useState(900);
  const [fit, setFit] = useState(false);
  const marker = `network-${useId().replaceAll(":", "")}`;
  const scale = fit ? Math.min(1, viewportWidth / layout.width) : zoom;
  const positions = new Map(layout.nodes.map(node => [node.stage.stage_id, node]));
  const visibleSelection = positions.has(selected ?? "") ? selected : null;
  const related = new Set([visibleSelection]);
  for (const edge of layout.edges) if (edge.from === visibleSelection || edge.to === visibleSelection) { related.add(edge.from); related.add(edge.to); }
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(entries => setViewportWidth(entries[0].contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const autoFocused = useRef<string | null>(null);
  useEffect(() => {
    const node = layout.nodes.find(item => item.stage.stage_id === currentId);
    if (!node || !viewport.current || autoFocused.current === currentId) return;
    autoFocused.current = currentId!;
    onSelect(node.stage.stage_id);
    viewport.current.scrollTo({ left: Math.max(0, node.x + NODE_WIDTH / 2 - viewport.current.clientWidth / 2), top: Math.max(0, node.y - 32), behavior: "instant" });
  }, [currentId, layout, onSelect]);
  const focusCurrent = () => {
    const node = positions.get(currentId ?? "");
    if (!node || !viewport.current) return;
    onSelect(node.stage.stage_id);
    viewport.current.scrollTo({ left: Math.max(0, (node.x + NODE_WIDTH / 2) * scale - viewport.current.clientWidth / 2), top: Math.max(0, node.y * scale - 32), behavior: "smooth" });
  };
  return <>
    <div className="s2-network-tools">
      <div><strong>Связи между работами</strong><span>Слева направо — порядок выполнения, расстояние не означает время</span></div>
      <div className="s2-network-actions">
        <button aria-label="Уменьшить сетевой график" disabled={scale <= .5} onClick={() => { setZoom(Math.max(.5, scale - .25)); setFit(false); }}>−</button>
        <span aria-live="polite">{Math.round(scale * 100)}%</span>
        <button aria-label="Увеличить сетевой график" disabled={!fit && zoom >= 1.5} onClick={() => { setZoom(Math.min(1.5, Math.max(.5, scale + .25))); setFit(false); }}>+</button>
        <button aria-pressed={fit} onClick={() => { setFit(value => !value); }}>Вместить</button>
        <button aria-pressed={Boolean(currentId && visibleSelection === currentId)} disabled={!positions.has(currentId ?? "")} onClick={focusCurrent}>К текущему этапу</button>
      </div>
    </div>
    {showCritical && stages.some(s=>s.is_critical) && !layout.edges.some(edge=>criticalEdge(positions.get(edge.from)?.stage,positions.get(edge.to)?.stage)) && <p className="s2-network-hint">Критические работы выделены карточками. Прямых критических связей между ними нет.</p>}
    {layout.hiddenPredecessors > 0 && <p className="s2-network-hint">Часть предшественников скрыта фильтрами. Чтобы увидеть все связи, сбросьте фильтры.</p>}
    {layout.cyclic && <p className="s2-network-hint" role="alert">В связях есть цикл. Откройте работу и исправьте предшественников; порядок узлов пока не рассчитан.</p>}
    <div className="s2-network-viewport" ref={viewport} tabIndex={0} aria-label="Сетевой график работ. Прокрутка по горизонтали и вертикали">
      <div style={{ width: layout.width * scale, height: layout.height * scale }}>
        <div className="s2-network-canvas" style={{ width: layout.width, height: layout.height, transform: `scale(${scale})` }}>
          <svg width={layout.width} height={layout.height} aria-hidden="true" className="s2-network-edges">
            <defs><marker id={marker} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 8 4 0 8z" fill="context-stroke" /></marker></defs>
            {layout.edges.map(edge => {
              const from = positions.get(edge.from)!, to = positions.get(edge.to)!;
              const highlighted = edge.from === visibleSelection || edge.to === visibleSelection;
              const critical = showCritical && criticalEdge(from.stage,to.stage);
              const x1 = from.x + NODE_WIDTH, y1 = from.y + NODE_HEIGHT / 2, x2 = to.x - 6, y2 = to.y + NODE_HEIGHT / 2;
              const curve = x2 > x1 ? `M${x1},${y1} C${x1 + 38},${y1} ${x2 - 38},${y2} ${x2},${y2}` : `M${x1},${y1} C${x1 + 46},${y1 + 100} ${x2 - 46},${y2 + 100} ${x2},${y2}`;
              return <path key={`${edge.from}-${edge.to}`} d={curve} className={`${critical ? "is-critical" : ""} ${highlighted ? "is-highlighted" : ""} ${visibleSelection && !highlighted ? "is-muted" : ""}`} markerEnd={`url(#${marker})`} />;
            })}
          </svg>
          {layout.nodes.map(({ stage, x, y }, index) => <article key={stage.stage_id} className={`s2-network-node ${paused ? "is-paused" : ""} ${showCritical && stage.is_critical ? "is-critical" : ""} ${visibleSelection === stage.stage_id ? "is-selected" : ""} ${visibleSelection && !related.has(stage.stage_id) ? "is-muted" : ""} ${currentId === stage.stage_id ? "is-current" : ""}`} style={{ left: x, top: y, width: NODE_WIDTH, height: NODE_HEIGHT }}>
            <button className="s2-network-node-main" onClick={() => onOpen(stage.stage_id)} aria-label={`Открыть работу ${stage.work_name}`}>
              <span className="s2-network-node-top"><span>{stage.work_code || `Работа ${index + 1}`}</span><b>{durationDays(stage.planned_start_date, stage.planned_end_date)} дн.</b></span>
              <strong title={stage.work_name}>{stage.work_name}</strong>
              <span className="s2-network-node-dates">{formatPlanDate(stage.planned_start_date)} <span>→</span> {formatPlanDate(stage.planned_end_date)}</span>
            </button>
            <div className="s2-network-node-bottom"><span title={stage.state_label_ru}>{paused ? "Приостановлен" : stage.state_label_ru || "Нет данных"}</span><button aria-label={`Показать связи: ${stage.work_name}`} aria-pressed={visibleSelection === stage.stage_id} onClick={() => onSelect(visibleSelection === stage.stage_id ? "" : stage.stage_id)}>Связи {stage.predecessor_ids.length}</button></div>
          </article>)}
        </div>
      </div>
    </div>
    <div className="s2-network-hint">{layout.nodes.length} работ · {layout.edges.length} связей. Нажмите на работу для просмотра и редактирования. «Связи» выделяет её непосредственных предшественников и последователей.</div>
  </>;
}
