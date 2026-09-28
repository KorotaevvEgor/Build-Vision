"""Обогащение результата проверки снимка данными языковой модели.

Ядро сопоставления (`matching.py`) отвечает на вопрос «соответствует ли
состав техники правилам активного этапа». Этот модуль добавляет к его
результату три вещи, которых там принципиально нет:

* оценку стадии и готовности объекта по самой фотографии — независимый от
  детектора источник, видящий здание, а не только машины вокруг него;
* расхождение между тем, что видно на снимке, и тем, что стоит в графике —
  отдельный тип отклонения уровня проекта;
* связное заключение для руководителя проекта на естественном языке.

Модуль никогда не роняет анализ снимка: если языковая модель недоступна,
возвращаются структуры с ``available=False``, а основной результат проверки
остаётся полностью рабочим.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from pathlib import Path

from . import activity as activity_module
from . import frame_zones as frame_zones_module
from . import zone_deviations
from .llm import (
    STAGE_CATALOG,
    ObservationSummary,
    StageFact,
    assess_photo,
    build_conclusion,
    llm_is_configured,
)
from .llm.vision import UNDETERMINED_KEY

logger = logging.getLogger(__name__)


def apply_zones_and_activity(
    detections,
    *,
    camera_external_id: str | None,
    image_size: tuple[int, int],
    observed_date=None,
) -> None:
    """Проставляет каждой детекции зону кадра и признак активности.

    Изменяет объекты на месте: детекции дальше идут и в ядро сопоставления,
    и в сохранение, и в ответ API — копировать их трижды незачем.

    Без указанной камеры функция ничего не делает, и это правильно: зоны и
    история кадров имеют смысл только в привязке к конкретной камере.
    """
    if not camera_external_id:
        return

    zones = frame_zones_module.load_frame_zones(camera_external_id)
    previous_frames = frame_zones_module.load_previous_frames(
        camera_external_id, observed_date=observed_date
    )
    if not zones and not previous_frames:
        return

    for detection in detections:
        zone_hit = activity_module.assign_zone(detection.bbox, zones, image_size)
        verdict = activity_module.decide_activity(
            detection.bbox,
            detection.class_key,
            zone_hit,
            previous_frames,
            zones_defined=bool(zones),
        )
        if zone_hit is not None:
            detection.frame_zone_id = zone_hit.zone_id
            detection.frame_zone_name = zone_hit.zone_name
            detection.frame_zone_kind = zone_hit.zone_kind
        detection.activity = verdict.activity
        detection.activity_reason = verdict.reason


def ai_enrichment_enabled() -> bool:
    """Глобальный выключатель на случай демонстрации без интернета."""
    if os.environ.get("SK_DISABLE_LLM", "false").lower() == "true":
        return False
    return llm_is_configured()


def _stage_key_for_work_code(work_code: str) -> str | None:
    """Сопоставляет код работы из графика со стадией, различимой на снимке.

    Коды в графике заказчика иерархические (12.3.1, 12.3.7), поэтому
    сравнение идёт по префиксу: подпункт относится к той же стадии, что и
    его родитель.
    """
    if not work_code:
        return None
    normalized = work_code.strip().rstrip(".")
    for definition in STAGE_CATALOG:
        for code in definition.work_codes:
            if normalized == code or normalized.startswith(f"{code}."):
                return definition.key
    return None


def _active_stage_keys(stages_by_id: dict) -> set[str]:
    """Стадии, которые по графику должны идти на дату наблюдения."""
    keys: set[str] = set()
    for stage in stages_by_id.values():
        key = _stage_key_for_work_code(getattr(stage, "work_code", "") or "")
        if key:
            keys.add(key)
    return keys


def _quantities_from_detections(detections) -> dict[str, int]:
    counts: dict[str, int] = {}
    for detection in detections:
        if not detection.in_taxonomy:
            continue
        counts[detection.label_ru] = counts.get(detection.label_ru, 0) + 1
    return counts


def build_summary(
    *,
    zone_name: str,
    evaluation,
    vision,
    stages_by_id: dict,
    weather_notes: list[str] | None = None,
    idle_equipment: list[str] | None = None,
    uncovered_zones: list[str] | None = None,
    stage_mismatch: bool = False,
    critical_stage_ids: set[str] | None = None,
) -> ObservationSummary:
    """Собирает срез наблюдения, который уходит в языковую модель.

    Сроки этапа берутся из графика (`stages_by_id`), а не из результата
    проверки: в `StageEvaluation` дат нет, а без них модель не сможет
    связать наблюдение со сроком выполнения работ.
    """
    actual = _quantities_from_detections(evaluation.all_detections)
    critical_stage_ids = critical_stage_ids or set()
    stages = []
    for item in evaluation.stage_evaluations:
        stage = stages_by_id.get(item.stage_id)
        stages.append(
            StageFact(
                work_name=item.work_name,
                start_date=stage.start_date.isoformat() if stage else "",
                end_date=stage.end_date.isoformat() if stage else "",
                status_label=item.status_label_ru,
                # Отклонение на критическом пути весит больше остальных: оно прямо
                # двигает дату сдачи объекта, и заключение обязано это назвать.
                is_on_critical_path=item.stage_id in critical_stage_ids,
                required_equipment={
                    check.label_ru: check.required_qty for check in item.quantity_checks
                },
                actual_equipment=actual,
                missing_equipment=list(item.missing_required),
                unexpected_equipment=[d.label_ru for d in item.unexpected_detections],
                ambiguous_equipment=sorted({d.label_ru for d in item.ambiguous_detections}),
            )
        )

    return ObservationSummary(
        zone_name=zone_name,
        observed_date=evaluation.observed_date.isoformat() if evaluation.observed_date else None,
        date_confirmed=evaluation.date_confirmed,
        overall_status_label=evaluation.overall_status_label_ru,
        stages=stages,
        idle_equipment=idle_equipment or [],
        uncovered_zones=uncovered_zones or [],
        weather_notes=weather_notes or [],
        vision_stage_label=vision.stage_label if vision.available else None,
        vision_readiness_percent=vision.readiness_percent if vision.available else None,
        schedule_stage_mismatch=stage_mismatch,
    )


def enrich_observation(
    *,
    image_path: Path,
    image_sha256: str,
    zone_name: str,
    evaluation,
    schedule,
    weather_notes: list[str] | None = None,
    uncovered_zones: list[str] | None = None,
    critical_stage_ids: set[str] | None = None,
) -> dict:
    """Возвращает блок ``ai`` для ответа API по наблюдению.

    Никогда не бросает исключений: любая проблема превращается в честный
    признак недоступности, а анализ снимка остаётся валидным.
    """
    # Отклонения по зонам считаются всегда, даже когда языковая модель отключена:
    # это чистая геометрия и правила, к внешним сервисам они отношения не имеют.
    zone_findings = zone_deviations.detect_zone_deviations(
        evaluation.all_detections,
        has_active_stage=bool(evaluation.stage_evaluations),
        uncovered_zones=uncovered_zones or [],
    )
    zone_findings_payload = [zone_deviations.to_dict(item) for item in zone_findings]

    if not ai_enrichment_enabled():
        return {
            "enabled": False,
            "reason": "Языковая модель отключена или не настроен ключ доступа",
            "vision": None,
            "conclusion": None,
            "stage_mismatch": None,
            "zone_deviations": zone_findings_payload,
        }

    try:
        vision = assess_photo(image_path, image_sha256=image_sha256)
    except Exception:
        logger.exception("Оценка снимка языковой моделью не выполнена")
        return {
            "enabled": True,
            "reason": "Оценка снимка завершилась ошибкой",
            "vision": None,
            "conclusion": None,
            "stage_mismatch": None,
        }

    stages_by_id = {
        stage.stage_id: stage
        for stage in schedule.stages
        if stage.stage_id in {item.stage_id for item in evaluation.stage_evaluations}
    }

    # Расхождение считаем только когда есть что с чем сравнивать: модель
    # уверенно назвала стадию и в графике на эту дату есть активные этапы.
    schedule_keys = _active_stage_keys(stages_by_id)
    mismatch_detected = bool(
        vision.available
        and vision.stage_key != UNDETERMINED_KEY
        and vision.confidence in {"high", "medium"}
        and schedule_keys
        and vision.stage_key not in schedule_keys
    )
    stage_mismatch = None
    if mismatch_detected:
        expected = ", ".join(
            definition.label_ru
            for definition in STAGE_CATALOG
            if definition.key in schedule_keys
        )
        stage_mismatch = {
            "observed_stage": vision.stage_label,
            "scheduled_stages": expected,
            "message": (
                f"На снимке видна стадия «{vision.stage_label}», "
                f"а по графику на эту дату должна идти «{expected}». "
                "Требуется проверка фактического хода работ."
            ),
        }

    idle_equipment = [
        f"{d.label_ru}: {d.activity_reason}"
        for d in evaluation.all_detections
        if d.activity == "idle" and d.in_taxonomy
    ]
    danger_equipment = [
        d.label_ru for d in evaluation.all_detections if d.frame_zone_kind == "danger"
    ]

    summary = build_summary(
        zone_name=zone_name,
        evaluation=evaluation,
        vision=vision,
        stages_by_id=stages_by_id,
        weather_notes=weather_notes,
        idle_equipment=idle_equipment,
        uncovered_zones=uncovered_zones or [],
        stage_mismatch=mismatch_detected,
        critical_stage_ids=critical_stage_ids,
    )
    summary.equipment_in_danger_zone = danger_equipment

    try:
        conclusion = build_conclusion(summary)
    except Exception:
        logger.exception("Заключение языковой модели не сформировано")
        conclusion = None

    return {
        "enabled": True,
        "reason": None,
        "vision": asdict(vision),
        "conclusion": (
            {
                "available": conclusion.available,
                "text": conclusion.text,
                "model": conclusion.model,
                "cached": conclusion.cached,
                "error": conclusion.error,
            }
            if conclusion is not None
            else {"available": False, "text": "", "error": "внутренняя ошибка при обращении к модели"}
        ),
        "stage_mismatch": stage_mismatch,
        "zone_deviations": zone_findings_payload,
    }
