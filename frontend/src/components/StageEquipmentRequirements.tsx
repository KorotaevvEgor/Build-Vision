import type { StageRequiredItemDetail } from "../api";
import { EquipmentIcon } from "./EquipmentIcons";
import "./StageEquipmentRequirements.css";

export function StageEquipmentRequirements({ items }: { items?: StageRequiredItemDetail[] }) {
  if (!items) return <p className="stage-equipment-empty">Требования к технике недоступны.</p>;
  if (!items.length) return <p className="stage-equipment-empty">Количественные требования к технике не заданы.</p>;
  return <div className="stage-equipment"><p className="stage-equipment-caption">Минимальное количество по плану этапа</p><ul>{items.map(item => <li key={item.class_key}>
    <span className="stage-equipment-icon"><EquipmentIcon classKey={item.class_key} aria-hidden="true" /></span>
    <span className="stage-equipment-name">{item.label_ru}</span>
    <strong>{item.min_quantity}<small>ед.</small></strong>
  </li>)}</ul></div>;
}
