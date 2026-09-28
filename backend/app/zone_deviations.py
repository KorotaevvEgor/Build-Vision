"""Отклонения, которые видны только через зоны кадра и активность техники.

Ядро сопоставления (`matching.py`) проверяет состав техники: хватает ли её по
количеству и нет ли лишней. Эти четыре отклонения оно увидеть не может в
принципе, потому что для них нужно знать, где именно на кадре стоит машина:

* техника простаивает, хотя этап активен;
* техника находится в опасной зоне;
* техника стоит вне рабочей зоны при активном этапе;
* зона графика вообще не покрыта камерами — работы идут вне контроля.

Последний пункт — дословное пожелание постановщиков: предупреждать, что часть
площадки находится вне контроля ИИ и требует дополнительной проверки.
"""

from __future__ import annotations

from dataclasses import dataclass

SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"
SEVERITY_INFO = "info"


@dataclass(frozen=True)
class ZoneDeviation:
    kind: str
    severity: str
    title: str
    message: str
    equipment: list[str]


def _labels(detections) -> list[str]:
    """Названия техники без повторов, в порядке появления."""
    seen: list[str] = []
    for detection in detections:
        if detection.label_ru not in seen:
            seen.append(detection.label_ru)
    return seen


def detect_zone_deviations(
    detections,
    *,
    has_active_stage: bool,
    uncovered_zones: list[str],
) -> list[ZoneDeviation]:
    """Собирает отклонения по зонам и активности.

    ``has_active_stage`` важен: простой техники ночью или в день, когда по
    графику работ нет, нарушением не является. Обвинять подрядчика в простое
    вне рабочего этапа было бы неверно.
    """
    deviations: list[ZoneDeviation] = []
    relevant = [d for d in detections if d.in_taxonomy and not d.ambiguous]

    in_danger = [d for d in relevant if d.frame_zone_kind == "danger"]
    if in_danger:
        deviations.append(
            ZoneDeviation(
                kind="equipment_in_danger_zone",
                severity=SEVERITY_CRITICAL,
                title="Техника в опасной зоне",
                message=(
                    "В опасной зоне обнаружена техника: "
                    f"{', '.join(_labels(in_danger))}. Требуется немедленная проверка "
                    "соблюдения мер безопасности."
                ),
                equipment=_labels(in_danger),
            )
        )

    if has_active_stage:
        idle = [d for d in relevant if d.activity == "idle"]
        if idle:
            reasons = {d.activity_reason for d in idle if d.activity_reason}
            deviations.append(
                ZoneDeviation(
                    kind="equipment_idle",
                    severity=SEVERITY_WARNING,
                    title="Простой техники при активном этапе",
                    message=(
                        f"Простаивает техника: {', '.join(_labels(idle))}. "
                        + (" ".join(sorted(reasons)) if reasons else "")
                    ).strip(),
                    equipment=_labels(idle),
                )
            )

        out_of_place = [
            d
            for d in relevant
            if d.frame_zone_kind in {"parking", "entrance"} and d.activity != "working"
        ]
        if out_of_place:
            deviations.append(
                ZoneDeviation(
                    kind="equipment_out_of_work_zone",
                    severity=SEVERITY_WARNING,
                    title="Техника вне рабочей зоны",
                    message=(
                        "При активном этапе техника находится вне рабочего участка: "
                        f"{', '.join(_labels(out_of_place))}. Проверьте, задействована ли она в работах."
                    ),
                    equipment=_labels(out_of_place),
                )
            )

    if uncovered_zones:
        deviations.append(
            ZoneDeviation(
                kind="zone_not_covered",
                severity=SEVERITY_INFO,
                title="Часть площадки вне контроля",
                message=(
                    "Следующие зоны не покрыты камерами с размеченными рабочими участками: "
                    f"{', '.join(uncovered_zones)}. Ход работ там проверить по снимкам нельзя, "
                    "требуется дополнительная проверка на месте."
                ),
                equipment=[],
            )
        )

    return deviations


def to_dict(deviation: ZoneDeviation) -> dict:
    return {
        "kind": deviation.kind,
        "severity": deviation.severity,
        "title": deviation.title,
        "message": deviation.message,
        "equipment": deviation.equipment,
    }
