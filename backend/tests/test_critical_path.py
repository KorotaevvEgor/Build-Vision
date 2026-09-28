"""Тесты расчёта критического пути.

Проверяется не «код не падает», а содержательные свойства расчёта: что запас
времени считается там, где он действительно есть, что отставание на критической
работе двигает дату сдачи, а внутри запаса — не двигает, и что цикл связей
честно объявляется нерасчётным вместо молчаливого выдавания чисел.
"""

from __future__ import annotations

from datetime import date

from app import critical_path


def stage(
    stage_id: str,
    start: str,
    end: str,
    *,
    parent: str | None = None,
    predecessors: tuple[str, ...] = (),
) -> critical_path.NetworkStage:
    return critical_path.NetworkStage(
        stage_id=stage_id,
        work_name=stage_id,
        zone_id="zone-a",
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
        parent_id=parent,
        predecessor_ids=predecessors,
    )


def test_empty_schedule_is_not_computable():
    result = critical_path.compute([])
    assert result.available is False
    assert "нет ни одного этапа" in result.reason


def test_single_chain_is_fully_critical():
    stages = [
        stage("a", "2026-01-01", "2026-01-10"),
        stage("b", "2026-01-11", "2026-01-20", predecessors=("a",)),
    ]
    result = critical_path.compute(stages)

    assert result.available is True
    assert result.project_finish == date(2026, 1, 20)
    assert result.critical_stage_ids == ["a", "b"]
    assert result.schedules["a"].total_float_days == 0


def test_parallel_branch_gets_float():
    """Короткая параллельная ветка не критична — у неё есть запас времени."""
    stages = [
        stage("long", "2026-01-01", "2026-01-20"),
        stage("short", "2026-01-01", "2026-01-05"),
        stage("final", "2026-01-21", "2026-01-25", predecessors=("long", "short")),
    ]
    result = critical_path.compute(stages)

    assert result.schedules["long"].total_float_days == 0
    assert result.schedules["short"].total_float_days == 15
    assert result.critical_stage_ids == ["final", "long"]


def test_delay_on_critical_stage_moves_project_finish():
    stages = [
        stage("a", "2026-01-01", "2026-01-10"),
        stage("b", "2026-01-11", "2026-01-20", predecessors=("a",)),
    ]
    baseline = critical_path.compute(stages)
    projected = critical_path.compute(stages, delays={"a": 5})

    assert (projected.project_finish - baseline.project_finish).days == 5


def test_delay_inside_float_does_not_move_project_finish():
    """Главное свойство: отставание в пределах запаса не двигает дату сдачи."""
    stages = [
        stage("long", "2026-01-01", "2026-01-20"),
        stage("short", "2026-01-01", "2026-01-05"),
        stage("final", "2026-01-21", "2026-01-25", predecessors=("long", "short")),
    ]
    baseline = critical_path.compute(stages)
    projected = critical_path.compute(stages, delays={"short": 10})

    assert projected.project_finish == baseline.project_finish


def test_delay_beyond_float_moves_project_finish():
    stages = [
        stage("long", "2026-01-01", "2026-01-20"),
        stage("short", "2026-01-01", "2026-01-05"),
        stage("final", "2026-01-21", "2026-01-25", predecessors=("long", "short")),
    ]
    baseline = critical_path.compute(stages)
    projected = critical_path.compute(stages, delays={"short": 20})

    assert (projected.project_finish - baseline.project_finish).days == 5


def test_early_start_pulls_project_finish_closer():
    stages = [
        stage("a", "2026-01-01", "2026-01-10"),
        stage("b", "2026-01-11", "2026-01-20", predecessors=("a",)),
    ]
    baseline = critical_path.compute(stages)
    projected = critical_path.compute(stages, start_overrides={"a": date(2026, 1, 1)})
    assert projected.project_finish == baseline.project_finish

    earlier = critical_path.compute(
        stages, start_overrides={"a": date(2025, 12, 25), "b": date(2026, 1, 5)}
    )
    assert earlier.project_finish < baseline.project_finish


def test_summary_stage_spans_children_and_has_no_own_dates():
    stages = [
        stage("group", "2026-01-01", "2026-01-31"),
        stage("child-1", "2026-01-01", "2026-01-10", parent="group"),
        stage("child-2", "2026-01-11", "2026-01-20", parent="group", predecessors=("child-1",)),
    ]
    result = critical_path.compute(stages)
    summary = result.schedules["group"]

    assert summary.is_summary is True
    assert summary.early_start == date(2026, 1, 1)
    assert summary.early_finish == date(2026, 1, 20)
    assert summary.level == 0
    assert result.schedules["child-2"].level == 1
    # Укрупнённая работа не попадает в перечень критических работ сама по себе.
    assert "group" not in result.critical_stage_ids


def test_dependency_on_summary_expands_to_its_leaves():
    """Связь с разделом должна означать связь со всеми работами внутри него."""
    stages = [
        stage("group", "2026-01-01", "2026-01-20"),
        stage("child-1", "2026-01-01", "2026-01-10", parent="group"),
        stage("child-2", "2026-01-01", "2026-01-20", parent="group"),
        stage("after", "2026-01-05", "2026-01-08", predecessors=("group",)),
    ]
    result = critical_path.compute(stages)

    # Работа после раздела не может начаться раньше окончания самой долгой работы внутри него.
    assert result.schedules["after"].early_start == date(2026, 1, 21)


def test_cycle_is_reported_instead_of_silent_numbers():
    stages = [
        stage("a", "2026-01-01", "2026-01-10", predecessors=("b",)),
        stage("b", "2026-01-11", "2026-01-20", predecessors=("a",)),
    ]
    result = critical_path.compute(stages)

    assert result.available is False
    assert result.cycle == ["a", "b"]
    assert not result.schedules


def test_unknown_predecessor_is_ignored_not_fatal():
    """Ссылка на удалённый этап не должна ломать весь график."""
    stages = [stage("a", "2026-01-01", "2026-01-10", predecessors=("gone",))]
    result = critical_path.compute(stages)

    assert result.available is True
    assert result.schedules["a"].early_start == date(2026, 1, 1)
