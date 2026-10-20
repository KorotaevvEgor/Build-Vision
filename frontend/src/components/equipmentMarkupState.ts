import { useState } from "react";
import type { DemoAnalysis, EquipmentCount } from "../api";

const CLASS_COLOR_VARS: Record<string, string> = {
  excavator: "var(--sk-class-excavator)",
  dump_truck: "var(--sk-class-dump-truck)",
  mobile_crane: "var(--sk-class-mobile-crane)",
  crane_manipulator: "var(--sk-class-crane-manipulator)",
  concrete_mixer: "var(--sk-class-concrete-mixer)",
  bulldozer: "var(--sk-class-bulldozer)",
  road_roller: "var(--sk-class-road-roller)",
  truck: "var(--sk-class-truck)",
};

export function classColor(classKey: string): string {
  return CLASS_COLOR_VARS[classKey] ?? "var(--sk-class-unknown)";
}

/** Кто нарисовал рамки: ИИ-модель (класс строго из нашего списка) или детектор YOLO-World. */
export type MarkupSource = "ai" | "detector";

export interface MarkupBox {
  id: string;
  classKey: string;
  label: string;
  confidence: number;
  /** Доли кадра 0..1 — не зависят от размера картинки на экране. */
  left: number;
  top: number;
  width: number;
  height: number;
  color: string;
  ambiguous: boolean;
}

export interface EquipmentMarkupState {
  source: MarkupSource;
  setSource: (source: MarkupSource) => void;
  hasAi: boolean;
  aiError: string | null;
  aiModel: string;
  boxes: MarkupBox[];
  counts: EquipmentCount[];
  /** Класс, на который навели курсор в списке или на рамке: остальные рамки приглушаются. */
  highlight: string | null;
  setHighlight: (classKey: string | null) => void;
}

/**
 * Единое состояние «фото с рамками + список техники»: и рамки, и список берутся из одного источника
 * (ИИ или детектор), чтобы то, что нарисовано на фото, всегда совпадало со списком рядом.
 * ИИ-разметка по умолчанию, если она доступна; иначе — честный откат на детектор.
 */
export function useEquipmentMarkup(
  result: DemoAnalysis | null,
  imageSize: { width: number; height: number } | null,
): EquipmentMarkupState {
  const [choice, setChoice] = useState<{ result: DemoAnalysis | null; source: MarkupSource } | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);

  const ai = result?.ai_equipment;
  const hasAi = Boolean(ai?.available);
  const defaultSource: MarkupSource = hasAi ? "ai" : "detector";
  // Выбор пользователя действует только для того результата, при котором он сделан: новый разбор
  // снова начинается с источника по умолчанию.
  const chosen = choice && choice.result === result ? choice.source : null;
  const source: MarkupSource = chosen === "ai" && !hasAi ? "detector" : (chosen ?? defaultSource);

  let boxes: MarkupBox[] = [];
  let counts: EquipmentCount[] = [];
  if (result && source === "ai" && ai) {
    boxes = ai.items.map((item, index) => ({
      id: `ai-${index}`,
      classKey: item.class_key,
      label: item.label_ru,
      confidence: item.confidence,
      left: item.box[0],
      top: item.box[1],
      width: item.box[2] - item.box[0],
      height: item.box[3] - item.box[1],
      color: classColor(item.class_key),
      ambiguous: false,
    }));
    counts = ai.counts;
  } else if (result) {
    if (imageSize) {
      boxes = result.detections.map((detection, index) => {
        const [x1, y1, x2, y2] = detection.bbox;
        return {
          id: `det-${index}`,
          classKey: detection.class_key,
          label: detection.label_ru,
          confidence: detection.confidence,
          left: x1 / imageSize.width,
          top: y1 / imageSize.height,
          width: (x2 - x1) / imageSize.width,
          height: (y2 - y1) / imageSize.height,
          color: detection.ambiguous
            ? "var(--sk-status-warning)"
            : !detection.in_taxonomy
              ? "var(--sk-class-unknown)"
              : classColor(detection.class_key),
          ambiguous: detection.ambiguous,
        };
      });
    }
    counts = result.equipment_counts;
  }

  return {
    source,
    setSource: (next) => setChoice({ result, source: next }),
    hasAi,
    aiError: ai && !ai.available ? ai.error : null,
    aiModel: ai?.model ?? "",
    boxes,
    counts,
    highlight,
    setHighlight,
  };
}
