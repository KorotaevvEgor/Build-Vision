import type { DeviationStatus } from "../api";
import "./StatusBadge.css";

const STATUS_STYLE: Record<DeviationStatus, { className: string }> = {
  no_deviation: { className: "sk-status-badge--ok" },
  possible_deviation: { className: "sk-status-badge--warning" },
  insufficient_data: { className: "sk-status-badge--unknown" },
};

interface StatusBadgeProps {
  status: DeviationStatus;
  label: string;
}

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const style = STATUS_STYLE[status];
  return <span className={`sk-status-badge ${style.className}`}>{label}</span>;
}
