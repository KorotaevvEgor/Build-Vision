"""Тесты определения работы и простоя техники.

Здесь легко ошибиться незаметно: геометрия работает «примерно правильно» и на
глаз выглядит верно, а ошибка проявляется на одном снимке из ста. Поэтому
проверяются именно граничные случаи — точка опоры машины, вложенные зоны,
кадр другого разрешения и порог смещения между снимками.
"""

from __future__ import annotations

from app import activity


def _zone(kind: str, polygon: list[list[float]], name: str = "зона", zone_id: int = 1) -> dict:
    return {
        "id": zone_id,
        "name": name,
        "kind": kind,
        "polygon": polygon,
        "reference_width": 1000,
        "reference_height": 800,
        "stage_id": None,
    }


LEFT_HALF = [[0, 0], [500, 0], [500, 800], [0, 800]]
RIGHT_HALF = [[500, 0], [1000, 0], [1000, 800], [500, 800]]


# --- Геометрия -------------------------------------------------------------


def test_point_inside_and_outside_polygon() -> None:
    square = [[0, 0], [100, 0], [100, 100], [0, 100]]
    assert activity.point_in_polygon((50, 50), square) is True
    assert activity.point_in_polygon((150, 50), square) is False


def test_point_in_concave_polygon() -> None:
    """Вогнутый полигон: выемка не должна считаться внутренней частью зоны.

    Рабочие зоны на реальных кадрах почти всегда вогнутые — их обводят по
    краю котлована, огибая отвалы грунта.
    """
    l_shape = [[0, 0], [100, 0], [100, 40], [40, 40], [40, 100], [0, 100]]
    assert activity.point_in_polygon((20, 20), l_shape) is True
    assert activity.point_in_polygon((70, 70), l_shape) is False


def test_zone_is_chosen_by_bottom_edge_not_center() -> None:
    """Машину определяет точка опоры, а не центр рамки.

    У экскаватора с поднятой стрелой центр рамки висит в воздухе и может
    оказаться в соседней зоне, тогда как сама машина стоит вполне определённо.
    Рамка здесь пересекает обе половины кадра, но опора — в правой.
    """
    zones = [_zone("parking", LEFT_HALF, "стоянка", 1), _zone("work", RIGHT_HALF, "котлован", 2)]
    # Рамка широкая: от x=400 до x=700, центр на x=550, опора тоже справа.
    hit = activity.assign_zone([400, 100, 700, 600], zones, (1000, 800))
    assert hit is not None
    assert hit.zone_kind == "work"


def test_danger_zone_wins_over_work_zone() -> None:
    """Опасная зона приоритетнее рабочей: это отклонение в любом случае."""
    overlapping_danger = [[400, 400], [600, 400], [600, 700], [400, 700]]
    zones = [
        _zone("work", [[0, 0], [1000, 0], [1000, 800], [0, 800]], "котлован", 1),
        _zone("danger", overlapping_danger, "зона крана", 2),
    ]
    hit = activity.assign_zone([480, 500, 520, 650], zones, (1000, 800))
    assert hit is not None
    assert hit.zone_kind == "danger"


def test_zone_polygon_is_rescaled_for_other_resolution() -> None:
    """Камера может прислать кадр другого размера — зона обязана подстроиться."""
    zones = [_zone("work", RIGHT_HALF, "котлован", 1)]
    # Кадр вдвое больше опорного: правая половина теперь начинается с x=1000.
    hit = activity.assign_zone([1200, 200, 1400, 1000], zones, (2000, 1600))
    assert hit is not None
    assert hit.zone_kind == "work"


def test_detection_outside_all_zones_returns_none() -> None:
    zones = [_zone("work", [[0, 0], [100, 0], [100, 100], [0, 100]], "котлован", 1)]
    assert activity.assign_zone([500, 500, 560, 560], zones, (1000, 800)) is None


# --- Определение активности ------------------------------------------------


def test_parking_zone_means_idle() -> None:
    zones = [_zone("parking", LEFT_HALF, "отстой", 1)]
    hit = activity.assign_zone([100, 100, 200, 300], zones, (1000, 800))
    verdict = activity.decide_activity([100, 100, 200, 300], "excavator", hit, [])
    assert verdict.activity == activity.ACTIVITY_IDLE
    assert "отстоя" in verdict.reason


def test_work_zone_means_working() -> None:
    zones = [_zone("work", RIGHT_HALF, "котлован", 1)]
    hit = activity.assign_zone([600, 100, 700, 300], zones, (1000, 800))
    verdict = activity.decide_activity([600, 100, 700, 300], "excavator", hit, [])
    assert verdict.activity == activity.ACTIVITY_WORKING


def test_small_movement_between_frames_means_working_even_in_parking_zone() -> None:
    """Заметное смещение узнаваемой машины сильнее признака по зоне.

    Разметка зон делается руками и может быть неточной, а факт перемещения —
    объективное наблюдение. Смещение здесь небольшое: машина остаётся
    узнаваемой как та же самая, поэтому перемещение доказано.
    """
    bbox = [100, 100, 200, 300]
    zones = [_zone("parking", LEFT_HALF, "отстой", 1)]
    hit = activity.assign_zone(bbox, zones, (1000, 800))
    previous = [[{"class_key": "excavator", "bbox": [140, 100, 240, 300]}]]
    verdict = activity.decide_activity(bbox, "excavator", hit, previous)
    assert verdict.activity == activity.ACTIVITY_WORKING
    assert "сместилась" in verdict.reason


def test_unmatched_machine_falls_back_to_zone_instead_of_claiming_movement() -> None:
    """Далёкая рамка — не доказательство перемещения.

    При съёмке раз в полчаса две разные машины одного класса легко принять
    за одну переехавшую. Когда пара не нашлась, система не выдумывает
    перемещение, а опирается на зону.
    """
    bbox = [100, 100, 200, 300]
    zones = [_zone("parking", LEFT_HALF, "отстой", 1)]
    hit = activity.assign_zone(bbox, zones, (1000, 800))
    far_away = [[{"class_key": "excavator", "bbox": [800, 100, 900, 300]}]]
    verdict = activity.decide_activity(bbox, "excavator", hit, far_away)
    assert verdict.activity == activity.ACTIVITY_IDLE
    assert "отстоя" in verdict.reason


def test_motionless_across_frames_means_idle_even_in_work_zone() -> None:
    """Машина в рабочей зоне, которая не двигается несколько кадров, простаивает."""
    bbox = [600, 100, 700, 300]
    zones = [_zone("work", RIGHT_HALF, "котлован", 1)]
    hit = activity.assign_zone(bbox, zones, (1000, 800))
    same_place = [{"class_key": "excavator", "bbox": [602, 101, 702, 301]}]
    verdict = activity.decide_activity(bbox, "excavator", hit, [same_place, same_place])
    assert verdict.activity == activity.ACTIVITY_IDLE
    assert "не сдвинулась" in verdict.reason


def test_single_motionless_frame_is_not_enough_for_idle() -> None:
    """Один совпавший кадр — не доказательство: машина могла попасть в паузу."""
    bbox = [600, 100, 700, 300]
    same_place = [{"class_key": "excavator", "bbox": [601, 100, 701, 300]}]
    verdict = activity.decide_activity(bbox, "excavator", None, [same_place])
    assert verdict.activity != activity.ACTIVITY_IDLE


def test_no_zones_and_no_history_is_honest_unknown() -> None:
    """Без зон и без истории система обязана признать, что данных нет."""
    verdict = activity.decide_activity([10, 10, 50, 50], "excavator", None, [])
    assert verdict.activity == activity.ACTIVITY_UNKNOWN
    assert "Недостаточно данных" in verdict.reason


def test_machine_of_other_class_is_not_matched_between_frames() -> None:
    """Самосвал на месте экскаватора — это другая машина, а не тот же простой."""
    bbox = [600, 100, 700, 300]
    previous = [{"class_key": "dump_truck", "bbox": [600, 100, 700, 300]}]
    assert activity.find_same_machine(bbox, "excavator", previous) is None
