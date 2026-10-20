export const NODE_WIDTH = 264;
export const NODE_HEIGHT = 142;
export const COLUMN_GAP = 76;
export const LANE_GAP = 30;
export const PADDING = 32;

interface LinkedStage {
  stage_id: string;
  predecessor_ids: string[];
  planned_start_date: string;
}

/** Position work nodes by dependency depth, without inventing missing links. */
export function networkLayout<T extends LinkedStage>(stages: T[]) {
  const byId = new Map(stages.map(stage => [stage.stage_id, stage]));
  const successors = new Map<string, string[]>();
  const indegree = new Map<string, number>();
  const ranks = new Map<string, number>();
  const edges: { from: string; to: string }[] = [];
  let hiddenPredecessors = 0;
  for (const stage of stages) {
    const predecessors = [...new Set(stage.predecessor_ids)];
    indegree.set(stage.stage_id, predecessors.filter(id => byId.has(id)).length);
    ranks.set(stage.stage_id, 0);
    for (const id of predecessors) {
      if (!byId.has(id)) { hiddenPredecessors++; continue; }
      successors.set(id, [...(successors.get(id) ?? []), stage.stage_id]);
      edges.push({ from: id, to: stage.stage_id });
    }
  }
  const queue = stages.filter(stage => indegree.get(stage.stage_id) === 0).map(stage => stage.stage_id);
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i];
    for (const next of successors.get(id) ?? []) {
      ranks.set(next, Math.max(ranks.get(next)!, ranks.get(id)! + 1));
      indegree.set(next, indegree.get(next)! - 1);
      if (indegree.get(next) === 0) queue.push(next);
    }
  }
  const cyclic = queue.length !== stages.length;
  // Keep every node available for repairing a malformed graph.
  const unresolved = stages.filter(stage => indegree.get(stage.stage_id)! > 0);
  if (unresolved.length) {
    const lastRank = Math.max(0, ...queue.map(id => ranks.get(id)!));
    for (const stage of unresolved) ranks.set(stage.stage_id, lastRank + 1);
  }
  const lanes = new Map<number, number>();
  const nodes = [...stages].sort((a, b) => ranks.get(a.stage_id)! - ranks.get(b.stage_id)! || a.planned_start_date.localeCompare(b.planned_start_date) || a.stage_id.localeCompare(b.stage_id)).map(stage => {
    const rank = ranks.get(stage.stage_id)!;
    const lane = lanes.get(rank) ?? 0;
    lanes.set(rank, lane + 1);
    return { stage, rank, x: PADDING + rank * (NODE_WIDTH + COLUMN_GAP), y: PADDING + lane * (NODE_HEIGHT + LANE_GAP) };
  });
  return {
    nodes, edges, cyclic, hiddenPredecessors,
    width: Math.max(600, ...nodes.map(node => node.x + NODE_WIDTH + PADDING)),
    height: Math.max(280, ...nodes.map(node => node.y + NODE_HEIGHT + PADDING)),
  };
}
