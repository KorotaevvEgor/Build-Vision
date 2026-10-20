import type { AiEquipment, Detection } from "../api";

type VisualObservation = {
  detections: Detection[];
  ai_equipment?: Pick<AiEquipment, "available" | "items"> | null;
};

/** Convert only the display layer; YOLO evidence and plan/fact remain unchanged. */
export function getDashboardDetections(
  observation: VisualObservation | null,
  imageSize: { width: number; height: number } | null,
): Detection[] {
  if (!observation) return [];
  const ai = observation.ai_equipment;
  if (!ai?.available) return observation.detections;
  if (!imageSize || imageSize.width <= 0 || imageSize.height <= 0) return [];
  return ai.items.filter((item) => {
    const [x1, y1, x2, y2] = item.box;
    return item.box.every(Number.isFinite) && x1 >= 0 && y1 >= 0 && x1 < x2 && y1 < y2 && x2 <= 1 && y2 <= 1;
  }).map((item) => ({
    class_key: item.class_key, label_ru: item.label_ru, confidence: item.confidence,
    bbox: [item.box[0] * imageSize.width, item.box[1] * imageSize.height,
      item.box[2] * imageSize.width, item.box[3] * imageSize.height],
    in_taxonomy: true, ambiguous: false, runner_up_class_key: null,
  }));
}
