"""Автоматические сценарии ядра сопоставления (методика, раздел плана).

Работают на синтетических детекциях — без реальной модели, быстро и
детерминированно. Каждый тест — один обязательный сценарий проверки
качества из плана.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.detector import Detection
from app.matching import (
    STATUS_INSUFFICIENT_DATA,
    STATUS_NO_DEVIATION,
    STATUS_POSSIBLE_DEVIATION,
    evaluate_observation,
)
from app.rules_config import EquipmentRules, StageRule
from app.schedule import Schedule, Stage


def stage(
    stage_id: str,
    zone_id: str = "zone-a",
    start: date = date(2026, 9, 10),
    end: date = date(2026, 9, 22),
) -> Stage:
    return Stage(
        stage_id=stage_id,
        work_code="",
        work_name=stage_id,
        zone_id=zone_id,
        start_date=start,
        end_date=end,
        technology_assumption="",
        is_demo=True,
    )


def rules(
    stage_rules: dict[str, StageRule],
    confusable_pairs: list[tuple[str, str]] | None = None,
) -> EquipmentRules:
    return EquipmentRules(
        stage_rules=stage_rules,
        ambiguity_margin=0.15,
        confusable_class_pairs=confusable_pairs or [("excavator", "crane_manipulator")],
    )


def det(
    class_key: str,
    confidence: float = 0.9,
    in_taxonomy: bool = True,
    ambiguous: bool = False,
    runner_up: str | None = None,
) -> Detection:
    return Detection(
        class_key=class_key,
        label_ru=class_key,
        in_taxonomy=in_taxonomy,
        confidence=confidence,
        bbox=[0, 0, 10, 10],
        ambiguous=ambiguous,
        runner_up_class_key=runner_up,
        runner_up_confidence=None,
    )


KOTLOVAN_RULE = StageRule(
    stage_id="stage-kotlovan",
    work_name="Устройство котлована",
    required=["excavator", "dump_truck"],
    allowed=["mobile_crane"],
    alternatives_note="",
)


# 1. Вся требуемая техника присутствует -> нет отклонений.
def test_no_deviation_when_all_required_present() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_NO_DEVIATION
    assert result.stage_evaluations[0].missing_required == []


# 2. Допустимая (не обязательная) техника не мешает "нет отклонений".
def test_allowed_extra_equipment_does_not_cause_deviation() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck"), det("mobile_crane")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_NO_DEVIATION


# 3. Отсутствие требуемой техники -> возможное отклонение.
def test_missing_required_equipment_is_possible_deviation() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_POSSIBLE_DEVIATION
    assert result.stage_evaluations[0].missing_required == ["dump_truck"]


# 4. Полное отсутствие детекций -> все требуемые классы отсутствуют.
def test_no_detections_flags_all_required_missing() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_POSSIBLE_DEVIATION
    assert set(result.stage_evaluations[0].missing_required) == {"excavator", "dump_truck"}


# 5. Неожиданная техника вне required+allowed -> возможное отклонение.
def test_unexpected_equipment_is_possible_deviation() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck"), det("bulldozer")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_POSSIBLE_DEVIATION
    assert result.stage_evaluations[0].unexpected_detections[0].class_key == "bulldozer"


# 6. Классы вне таксономии (люди, машины) не считаются неожиданной техникой.
def test_distractor_classes_are_not_unexpected_equipment() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck"), det("person", in_taxonomy=False)],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_NO_DEVIATION


# 7. Требуемый класс обнаружен только как неоднозначная детекция
#    известного перепутываемого класса -> "Недостаточно данных", не отклонение.
def test_ambiguous_confusable_partner_gives_insufficient_data() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[
            det("crane_manipulator", ambiguous=True, runner_up="excavator"),
            det("dump_truck"),
        ],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_INSUFFICIENT_DATA


# 8. Без подтверждённой даты — всегда "Недостаточно данных".
def test_unconfirmed_date_is_always_insufficient_data() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=False,
        detections=[det("excavator"), det("dump_truck")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_INSUFFICIENT_DATA
    assert result.stage_evaluations == []


# 9. Дата без активного этапа в графике -> "Недостаточно данных".
def test_date_without_active_stage_is_insufficient_data() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 1, 1),
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_INSUFFICIENT_DATA
    assert result.stage_evaluations == []


# 10. Этап есть в графике, но для него не задано правило техники.
def test_stage_without_rule_is_insufficient_data() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-no-rule")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator")],
        schedule=schedule,
        rules=rules({}),
    )
    assert result.overall_status == STATUS_INSUFFICIENT_DATA


# 11. Соседняя зона: техника в другой зоне не спасает от отклонения в этой.
def test_neighbouring_zone_does_not_share_detections() -> None:
    schedule = Schedule(
        is_demo=True,
        stages=[stage("stage-kotlovan", zone_id="zone-a"), stage("stage-b", zone_id="zone-b")],
    )
    # Детекции относятся к снимку зоны A — но проверяем зону A: техники нет.
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[],
        schedule=schedule,
        rules=rules(
            {
                "stage-kotlovan": KOTLOVAN_RULE,
                "stage-b": StageRule("stage-b", "Работа Б", ["road_roller"], [], ""),
            }
        ),
    )
    # Проверяется только зона A; этап зоны Б не должен попасть в оценку.
    assert {e.stage_id for e in result.stage_evaluations} == {"stage-kotlovan"}


# 12. Параллельные работы в одной зоне: техника, допустимая для второго
#     этапа, не считается неожиданной для первого (union по зоне).
def test_parallel_stage_allowed_equipment_is_not_unexpected() -> None:
    schedule = Schedule(
        is_demo=True,
        stages=[
            stage("stage-kotlovan", zone_id="zone-a"),
            stage("stage-uplotnenie", zone_id="zone-a"),
        ],
    )
    rule_set = rules(
        {
            "stage-kotlovan": KOTLOVAN_RULE,
            "stage-uplotnenie": StageRule("stage-uplotnenie", "Уплотнение", ["road_roller"], [], ""),
        }
    )
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck"), det("road_roller")],
        schedule=schedule,
        rules=rule_set,
    )
    kotlovan_eval = next(e for e in result.stage_evaluations if e.stage_id == "stage-kotlovan")
    assert kotlovan_eval.unexpected_detections == []


# 13. Альтернативная технология (класс из allowed) не считается нарушением
#     даже если это единственная присутствующая техника этого типа.
def test_alternative_allowed_technology_not_flagged() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck"), det("mobile_crane")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.stage_evaluations[0].status == STATUS_NO_DEVIATION


# 14. Изменение правил в конфигурации меняет результат без изменения кода.
def test_changing_rules_config_changes_outcome() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    detections = [det("excavator")]

    strict_rules = rules(
        {"stage-kotlovan": StageRule("stage-kotlovan", "Котлован", ["excavator", "dump_truck"], [], "")}
    )
    relaxed_rules = rules(
        {"stage-kotlovan": StageRule("stage-kotlovan", "Котлован", ["excavator"], [], "")}
    )

    strict_result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=detections,
        schedule=schedule,
        rules=strict_rules,
    )
    relaxed_result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=detections,
        schedule=schedule,
        rules=relaxed_rules,
    )
    assert strict_result.overall_status == STATUS_POSSIBLE_DEVIATION
    assert relaxed_result.overall_status == STATUS_NO_DEVIATION


# 15. Приоритет статусов: possible_deviation "перевешивает" no_deviation
#     среди нескольких активных этапов одной зоны/даты.
def test_overall_status_prioritises_possible_deviation() -> None:
    schedule = Schedule(
        is_demo=True,
        stages=[stage("stage-ok", zone_id="zone-a"), stage("stage-bad", zone_id="zone-a")],
    )
    rule_set = rules(
        {
            "stage-ok": StageRule("stage-ok", "OK", ["excavator"], [], ""),
            "stage-bad": StageRule("stage-bad", "BAD", ["road_roller"], [], ""),
        }
    )
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator")],
        schedule=schedule,
        rules=rule_set,
    )
    assert result.overall_status == STATUS_POSSIBLE_DEVIATION


# 16. Приоритет статусов: insufficient_data "перевешивает" no_deviation.
def test_overall_status_prioritises_insufficient_data_over_no_deviation() -> None:
    schedule = Schedule(
        is_demo=True,
        stages=[stage("stage-ok", zone_id="zone-a"), stage("stage-no-rule", zone_id="zone-a")],
    )
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator")],
        schedule=schedule,
        rules=rules({"stage-ok": StageRule("stage-ok", "OK", ["excavator"], [], "")}),
    )
    assert result.overall_status == STATUS_INSUFFICIENT_DATA


# 17. Неоднозначная детекция, не относящаяся ни к одному активному правилу,
#     не должна ложно понижать статус до "Недостаточно данных".
def test_irrelevant_ambiguous_detection_does_not_block_no_deviation() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[
            det("excavator"),
            det("dump_truck"),
            det("mobile_crane", ambiguous=True, runner_up="crane_manipulator"),
        ],
        schedule=schedule,
        rules=rules(
            {"stage-kotlovan": KOTLOVAN_RULE},
            confusable_pairs=[("mobile_crane", "crane_manipulator")],
        ),
    )
    # mobile_crane допустим для этапа, неоднозначность не про требуемый класс —
    # ожидаем "нет отклонений", а не ложную тревогу неопределённости.
    assert result.overall_status == STATUS_NO_DEVIATION


# 18. Дата вне диапазона графика в обе стороны (раньше и позже) — оба случая.
@pytest.mark.parametrize("query_date", [date(2026, 9, 9), date(2026, 9, 23)])
def test_date_just_outside_stage_range_is_insufficient_data(query_date: date) -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=query_date,
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_INSUFFICIENT_DATA


# 19. Границы диапазона включительно: первый и последний день этапа активны.
@pytest.mark.parametrize("query_date", [date(2026, 9, 10), date(2026, 9, 22)])
def test_stage_range_boundaries_are_inclusive(query_date: date) -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=query_date,
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_NO_DEVIATION


# 20. Неизвестная зона (не связанная ни с одним этапом графика) не даёт
#     никаких этапов для оценки — результат "Недостаточно данных".
def test_unknown_zone_has_no_stages_to_evaluate() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan", zone_id="zone-a")])
    result = evaluate_observation(
        zone_id="zone-does-not-exist",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.overall_status == STATUS_INSUFFICIENT_DATA
    assert result.stage_evaluations == []


# 21. Несколько требуемых классов отсутствуют одновременно — оба перечислены.
def test_multiple_missing_required_are_all_listed() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-mix")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("truck")],
        schedule=schedule,
        rules=rules(
            {
                "stage-mix": StageRule(
                    "stage-mix", "Смешанный этап", ["excavator", "dump_truck", "road_roller"], [], ""
                )
            }
        ),
    )
    assert set(result.stage_evaluations[0].missing_required) == {
        "excavator",
        "dump_truck",
        "road_roller",
    }


KOTLOVAN_RULE_WITH_QUANTITIES = StageRule(
    stage_id="stage-kotlovan",
    work_name="Устройство котлована",
    required=["excavator", "dump_truck"],
    allowed=["mobile_crane"],
    alternatives_note="",
    required_quantities={"excavator": 1, "dump_truck": 3},
)


# 22. Частичное количество (1 из 3 самосвалов) -> возможное отклонение,
#     даже если класс как таковой обнаружен (не в missing_required).
def test_partial_quantity_shortfall_is_possible_deviation() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE_WITH_QUANTITIES}),
    )
    stage_eval = result.stage_evaluations[0]
    assert result.overall_status == STATUS_POSSIBLE_DEVIATION
    assert stage_eval.missing_required == []  # класс присутствует, просто не в нужном количестве
    dump_truck_check = next(c for c in stage_eval.quantity_checks if c.class_key == "dump_truck")
    assert dump_truck_check.required_qty == 3
    assert dump_truck_check.actual_qty == 1
    assert dump_truck_check.satisfied is False


# 23. Избыток техники сверх плана (5 самосвалов вместо 3) -> не нарушение.
def test_quantity_surplus_is_not_a_deviation() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), *[det("dump_truck") for _ in range(5)]],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE_WITH_QUANTITIES}),
    )
    stage_eval = result.stage_evaluations[0]
    assert result.overall_status == STATUS_NO_DEVIATION
    dump_truck_check = next(c for c in stage_eval.quantity_checks if c.class_key == "dump_truck")
    assert dump_truck_check.actual_qty == 5
    assert dump_truck_check.satisfied is True


# 24. Точное соответствие плану по количеству -> нет отклонений, оба
#     quantity_checks помечены как satisfied.
def test_exact_quantity_match_is_satisfied_for_all_classes() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), *[det("dump_truck") for _ in range(3)]],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE_WITH_QUANTITIES}),
    )
    stage_eval = result.stage_evaluations[0]
    assert result.overall_status == STATUS_NO_DEVIATION
    assert all(c.satisfied for c in stage_eval.quantity_checks)


# 25. Правило без required_quantities (старый формат) не считает количество —
#     quantity_checks пуст, поведение как раньше (только присутствие/отсутствие).
def test_rule_without_quantities_has_empty_quantity_checks() -> None:
    schedule = Schedule(is_demo=True, stages=[stage("stage-kotlovan")])
    result = evaluate_observation(
        zone_id="zone-a",
        observed_date=date(2026, 9, 15),
        date_confirmed=True,
        detections=[det("excavator"), det("dump_truck")],
        schedule=schedule,
        rules=rules({"stage-kotlovan": KOTLOVAN_RULE}),
    )
    assert result.stage_evaluations[0].quantity_checks == []
