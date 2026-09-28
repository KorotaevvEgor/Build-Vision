/**
 * Общие URL тайлов для всех Leaflet-карт приложения (MapPage, SiteBoundaryMap).
 * Вынесено в один модуль, чтобы переключение "схема/спутник" было одинаковым
 * везде и не расходилось при правках отдельных карт.
 */

export type MapLayerKind = "street" | "satellite";

export const STREET_TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";

// Esri World Imagery — бесплатный спутниковый слой без ключа API, тот же
// провайдер, что часто используют вместе с Leaflet как замену Google Maps.
export const SATELLITE_TILE_URL =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

export function tileUrlFor(layer: MapLayerKind): string {
  return layer === "satellite" ? SATELLITE_TILE_URL : STREET_TILE_URL;
}
