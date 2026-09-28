"""Определение факта работы и факта простоя техники.

Требование прозвучало от постановщиков задачи жёстко: «Иначе не получится.
Безусловно, нужно определять факт работы и факт простоя техники». Способ они
подсказали сами — смотреть, в какой зоне техника находится на снимке.

Мы используем два независимых признака, и это принципиально: каждый из них по
отдельности ошибается, а вместе они дают объяснимый ответ.

Первый признак — зона. Экскаватор в рабочей зоне котлована и тот же экскаватор
у въезда на площадку означают разное, даже если выглядят одинаково.

Второй признак — сравнение с предыдущими снимками той же камеры. Камеры
стационарные и снимают раз в 20-30 минут (это подтвердили постановщики),
поэтому кадры сопоставимы попиксельно: если машина не сдвинулась за несколько
кадров подряд, она стоит.

Важное ограничение второго признака, выявленное на тестах. Он доказывает только
простой — та же машина на том же месте. Доказать работу через перемещение
можно только тогда, когда мы уверены, что это та же самая машина. При
интервале в полчаса две разные машины одного класса легко перепутать, поэтому
если пара не нашлась в пределах допуска, мы не объявляем перемещение, а
переходим к признаку по зоне.

Когда ни один признак не сработал, честно возвращается «определить нельзя»,
а не догадка.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ACTIVITY_WORKING = "working"
ACTIVITY_IDLE = "idle"
ACTIVITY_UNKNOWN = "unknown"

# Насколько должен сместиться центр рамки между снимками, чтобы считать технику
# перемещавшейся. Доля от диагонали самой рамки, а не абсолютные пиксели: дальняя
# техника занимает меньше места в кадре и смещается на меньшее число пикселей.
MOVEMENT_THRESHOLD_RATIO = 0.12

# Сколько предыдущих снимков подряд машина должна простоять на месте.
# Один совпавший кадр ничего не доказывает: экскаватор мог просто попасть в паузу
# между движениями. Два кадра подряд при съёмке раз в полчаса — это уже час простоя.
IDLE_FRAMES_REQUIRED = 2

# Допуск при сопоставлении рамок между снимками: рамки одного класса, центры
# которых ближе этой доли диагонали, считаются одной и той же машиной.
MATCH_DISTANCE_RATIO = 0.6


@dataclass(frozen=True)
class ZoneHit:
    """Результат попадания детекции в зону кадра."""

    zone_id: int | None
    zone_name: str
    zone_kind: str
    stage_id: str | None


@dataclass(frozen=True)
class ActivityVerdict:
    activity: str
    reason: str


def _anchor_point(bbox: list[float] | tuple[float, ...]) -> tuple[float, float]:
    """Точка опоры машины — середина нижней грани рамки.

    Центр рамки для этого не годится: у экскаватора с поднятой стрелой и у крана
    центр висит в воздухе и может попасть в соседнюю зону, тогда как машина
    стоит совершенно определённо.
    """
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2, max(y1, y2)


def point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    """Проверка попадания точки в многоугольник методом трассировки луча.

    Своя реализация вместо shapely: зависимость ради одной функции на десяток
    строк не оправдана, а поведение здесь полностью предсказуемо.
    """
    x, y = point
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        intersects = (y1 > y) != (y2 > y)
        if not intersects:
            continue
        if y2 == y1:
            continue
        x_at_y = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        if x < x_at_y:
            inside = not inside
    return inside


def scale_polygon(
    polygon: list[list[float]],
    reference: tuple[int, int],
    actual: tuple[int, int],
) -> list[list[float]]:
    """Пересчитывает полигон, если камера прислала кадр другого разрешения."""
    ref_width, ref_height = reference
    width, height = actual
    if ref_width <= 0 or ref_height <= 0 or (ref_width == width and ref_height == height):
        return polygon
    scale_x = width / ref_width
    scale_y = height / ref_height
    return [[x * scale_x, y * scale_y] for x, y in polygon]


def assign_zone(
    bbox: list[float],
    frame_zones: list[dict],
    image_size: tuple[int, int],
) -> ZoneHit | None:
    """Находит зону, в которой стоит машина.

    Зоны проверяются в порядке приоритета: опасная зона важнее рабочей, потому
    что нахождение техники в ней — отклонение независимо от того, работает она
    или нет.
    """
    priority = {"danger": 0, "entrance": 1, "parking": 2, "work": 3, "uncontrolled": 4}
    anchor = _anchor_point(bbox)

    matches = []
    for zone in frame_zones:
        polygon = scale_polygon(
            zone["polygon"],
            (zone["reference_width"], zone["reference_height"]),
            image_size,
        )
        if len(polygon) >= 3 and point_in_polygon(anchor, polygon):
            matches.append(zone)

    if not matches:
        return None

    best = min(matches, key=lambda z: priority.get(z["kind"], 9))
    return ZoneHit(
        zone_id=best.get("id"),
        zone_name=best.get("name", ""),
        zone_kind=best["kind"],
        stage_id=best.get("stage_id"),
    )


def _diagonal(bbox: list[float] | tuple[float, ...]) -> float:
    x1, y1, x2, y2 = bbox
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def find_same_machine(
    bbox: list[float],
    class_key: str,
    previous_detections: list[dict],
) -> dict | None:
    """Ищет ту же машину на предыдущем снимке: тот же класс и близкий центр."""
    anchor = _anchor_point(bbox)
    tolerance = _diagonal(bbox) * MATCH_DISTANCE_RATIO
    candidates = [
        (
            _distance(anchor, _anchor_point(previous["bbox"])),
            previous,
        )
        for previous in previous_detections
        if previous.get("class_key") == class_key
    ]
    if not candidates:
        return None
    distance, best = min(candidates, key=lambda item: item[0])
    return best if distance <= tolerance else None


def decide_activity(
    bbox: list[float],
    class_key: str,
    zone_hit: ZoneHit | None,
    previous_frames: list[list[dict]],
    zones_defined: bool = False,
) -> ActivityVerdict:
    """Сводит два признака в один ответ с объяснением.

    ``previous_frames`` — детекции предыдущих снимков той же камеры, от самого
    свежего к более старым. ``zones_defined`` нужен только для точности
    формулировки: «зоны не размечены» и «машина вне размеченных зон» — разные
    ситуации, и инженер должен понимать, что именно ему делать.
    """
    # Признак по истории кадров сильнее: он не зависит от качества разметки зон.
    if previous_frames:
        anchor = _anchor_point(bbox)
        threshold = _diagonal(bbox) * MOVEMENT_THRESHOLD_RATIO
        motionless_frames = 0
        for frame in previous_frames[:IDLE_FRAMES_REQUIRED]:
            match = find_same_machine(bbox, class_key, frame)
            if match is None:
                break
            if _distance(anchor, _anchor_point(match["bbox"])) <= threshold:
                motionless_frames += 1
            else:
                return ActivityVerdict(
                    ACTIVITY_WORKING,
                    "Машина сместилась по сравнению с предыдущим снимком камеры",
                )
        if motionless_frames >= IDLE_FRAMES_REQUIRED:
            return ActivityVerdict(
                ACTIVITY_IDLE,
                f"Машина не сдвинулась на протяжении {motionless_frames} предыдущих снимков камеры",
            )

    if zone_hit is not None:
        if zone_hit.zone_kind == "parking":
            return ActivityVerdict(
                ACTIVITY_IDLE, f"Техника находится в зоне отстоя «{zone_hit.zone_name}»"
            )
        if zone_hit.zone_kind == "entrance":
            return ActivityVerdict(
                ACTIVITY_IDLE,
                f"Техника находится в зоне въезда «{zone_hit.zone_name}», а не на рабочем участке",
            )
        if zone_hit.zone_kind == "work":
            return ActivityVerdict(
                ACTIVITY_WORKING, f"Техника находится в рабочей зоне «{zone_hit.zone_name}»"
            )

    if zones_defined:
        return ActivityVerdict(
            ACTIVITY_UNKNOWN,
            "Машина находится вне размеченных зон кадра, истории предыдущих снимков недостаточно",
        )
    return ActivityVerdict(
        ACTIVITY_UNKNOWN,
        "Недостаточно данных: зоны на кадре не размечены и нет предыдущих снимков камеры",
    )
