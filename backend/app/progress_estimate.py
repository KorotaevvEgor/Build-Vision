"""Dates based only on a responsible person's recorded physical progress."""
from datetime import date, timedelta
from math import ceil

from .schedule import Stage


def estimate_finish(stage: Stage, today: date) -> tuple[date, str, bool]:
    percent = stage.verified_progress_percent
    measured = stage.verified_progress_date
    if not stage.verified_progress_note.strip() or measured is None or measured > today or percent is None or not 0 <= percent <= 100:
        return stage.end_date, "plan_reference_scenario", False
    if percent == 100:
        return measured, "manually_confirmed_completion", True
    if stage.expected_finish_date is not None:
        return stage.expected_finish_date, "responsible_person_estimate", False
    # A single dated measurement supports a constant average pace scenario only.
    # Never move its result forward merely because today's date has changed.
    if percent is not None and 0 < percent < 100 and measured >= stage.start_date:
        elapsed = (measured - stage.start_date).days + 1
        total_days = ceil(elapsed * 100 / percent)
        return stage.start_date + timedelta(days=total_days - 1), "constant_physical_pace_scenario", False
    return stage.end_date, "plan_reference_scenario", False
