import type {FrameZone} from "./api";
export const FRAME_ZONE_COLORS = {work:"#34d399",parking:"#60a5fa",entrance:"#fbbf24",danger:"#f87171",uncontrolled:"#94a3b8"};
export function frameZoneColor(zone: Pick<FrameZone,"kind"|"color">): string {return zone.color || FRAME_ZONE_COLORS[zone.kind];}
