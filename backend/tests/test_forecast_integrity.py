from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from app import forecast, schedule_network
from app.progress_estimate import estimate_finish
from app.schedule import Schedule, Stage


def stage(**kwargs):
    return Stage(stage_id="a", work_code="", work_name="A", zone_id="z", start_date=date(2026, 1, 1), end_date=date(2026, 1, 10), technology_assumption="", is_demo=False, **kwargs)


@pytest.mark.parametrize("status", ["no_deviation", "possible_deviation"])
def test_resource_observation_never_proves_completion_or_elapsed_delay(monkeypatch, status):
    obs = [SimpleNamespace(overall_status=status, observed_date=date(2026, 1, 2))]
    monkeypatch.setattr(schedule_network, "_confirmed_observations", lambda *a, **k: obs)
    row = schedule_network.estimate_progress(Schedule(False, [stage()]), date(2026, 10, 1))["a"]
    assert row.state == schedule_network.UNVERIFIED
    assert row.delay_days == 0
    assert not row.completion_confirmed


def test_resource_compliance_never_becomes_inverse_productivity(monkeypatch):
    monkeypatch.setattr(forecast, "_stage_observations", lambda *a, **k: [SimpleNamespace(overall_status="possible_deviation")])
    monkeypatch.setattr(forecast, "_latest_quantity_shortfalls", lambda *a: [])
    row = forecast.forecast_for_stage(stage=stage(), schedule=Schedule(False, [stage()]), weather_rules=[], latitude=0, longitude=0, today=date(2026, 1, 5), include_weather=False)
    assert row["average_compliance_percent"] == 0
    assert row["delay_days"] == 0
    assert row["physical_progress_percent"] is None


def test_dated_physical_progress_drives_stable_explained_scenario():
    work = stage(verified_progress_percent=25, verified_progress_date=date(2026, 1, 5), verified_progress_note="Measured 25 of 100 cubic metres")
    assert estimate_finish(work, date(2026, 1, 5)) == (date(2026, 1, 20), "constant_physical_pace_scenario", False)
    assert estimate_finish(work, date(2026, 10, 1))[0] == date(2026, 1, 20)


def test_only_dated_manual_full_progress_confirms_completion():
    work = stage(verified_progress_percent=100, verified_progress_date=date(2026, 1, 8), verified_progress_note="Acceptance act 12")
    assert estimate_finish(work, date(2026, 1, 9))[2] is True
    assert estimate_finish(replace(work, verified_progress_note=""), date(2026, 1, 9))[2] is False
    assert estimate_finish(work, date(2026, 1, 7))[2] is False


def test_responsible_finish_consumes_float_before_shifting_project(monkeypatch):
    monkeypatch.setattr(schedule_network, "_confirmed_observations", lambda *a, **k: [])
    a = replace(stage(), end_date=date(2026, 1, 2), verified_progress_percent=20, verified_progress_date=date(2026, 1, 1), verified_progress_note="Engineer estimate", expected_finish_date=date(2026, 1, 4))
    b = replace(stage(), stage_id="b", start_date=date(2026, 1, 6), end_date=date(2026, 1, 10), predecessor_ids=("a",))
    report = schedule_network.build_report(Schedule(False, [a, b]), date(2026, 1, 2))
    assert report.shift_days == 0
    assert not report.stages[0]["shifts_project_finish"]
    report = schedule_network.build_report(Schedule(False, [replace(a, expected_finish_date=date(2026, 1, 7)), b]), date(2026, 1, 2))
    assert report.shift_days == 2
    assert report.projected_finish == date(2026, 1, 12)
    assert report.stages[0]["shifts_project_finish"]
