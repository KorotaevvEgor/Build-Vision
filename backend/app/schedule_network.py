"""Сетевой график: план и сценарий на основе подтверждённых физических объёмов.

Ответственный фиксирует долю выполненных работ, дату и основание замера.
Ожидаемая дата имеет приоритет над сценарием сохранения среднего темпа.
Ресурсные проверки техники не доказывают начало, завершение или длительность.
Сдвиги дат передаются по связям с учётом резерва критического пути.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import critical_path, django_bridge
from .schedule import Schedule, Stage
from .progress_estimate import estimate_finish

#: Состояния работы по фактическим данным фотоконтроля.
NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
DONE_ON_TIME = "done_on_time"
OVERDUE = "overdue"
UNVERIFIED = "unverified"
STARTED_EARLY = "started_early"

STATE_LABELS = {
    NOT_STARTED: "Не начат",
    IN_PROGRESS: "Плановый период этапа",
    DONE_ON_TIME: "Завершён в срок",
    OVERDUE: "Просрочен",
    UNVERIFIED: "Срок истёк, завершение не подтверждено",
    STARTED_EARLY: "Начат досрочно",
}

BEHIND = "behind"
ON_TRACK = "on_track"
AHEAD = "ahead"

PROJECT_STATUS_LABELS = {
    BEHIND: "Отставание от графика",
    ON_TRACK: "Сдвиг не определён по имеющимся данным",
    AHEAD: "Опережение графика",
}


@dataclass
class StageProgress:
    """Фактическое состояние одной работы по данным фотоконтроля."""

    stage_id: str
    state: str
    delay_days: int = 0
    actual_start: date | None = None
    reason: str = ""
    observation_count: int = 0
    compliance_percent: float | None = None
    estimate_kind: str = "plan_reference_scenario"
    completion_confirmed: bool = False


@dataclass
class NetworkReport:
    available: bool
    reason: str = ""
    cycle: list[str] = field(default_factory=list)
    baseline_finish: date | None = None
    projected_finish: date | None = None
    shift_days: int = 0
    status: str = ON_TRACK
    stages: list[dict] = field(default_factory=list)
    critical_stage_ids: list[str] = field(default_factory=list)
    #: Работы с истёкшим сроком без единого подтверждающего снимка.
    unverified_stage_ids: list[str] = field(default_factory=list)


def build_network(schedule: Schedule) -> list[critical_path.NetworkStage]:
    return [
        critical_path.NetworkStage(
            stage_id=stage.stage_id,
            work_name=stage.work_name,
            zone_id=stage.zone_id,
            start_date=stage.start_date,
            end_date=stage.end_date,
            parent_id=stage.parent_id,
            predecessor_ids=stage.predecessor_ids,
            work_code=stage.work_code,
        )
        for stage in schedule.stages
    ]


def _confirmed_observations(stage: Stage, today: date, site=None) -> list:
    """Подтверждённые по дате наблюдения зоны за период этапа.

    Только подтверждённые: снимок с неизвестной или неподтверждённой датой
    нельзя отнести к периоду работы, а значит и судить по нему о сроках.
    """
    if not django_bridge.ensure_django_ready():
        return []
    from core.models import Observation

    site_filter = {"zone__site": site} if site is not None else {"zone__site__is_legacy": True}
    return list(
        Observation.objects.filter(
            zone__external_id=stage.zone_id,
            observed_date__gte=stage.start_date,
            observed_date__lte=min(today, stage.end_date),
            date_confirmed=True,
            **site_filter,
        ).order_by("observed_date")
    )


def _compliance(observations: list) -> float | None:
    if not observations:
        return None
    return sum(1 for o in observations if o.overall_status == "no_deviation") / len(observations)


def estimate_progress(schedule: Schedule, today: date, site=None) -> dict[str, StageProgress]:
    """Разделяет плановый период, ресурсные проверки и подтверждённые объёмы."""
    progress: dict[str, StageProgress] = {}
    children = {stage.parent_id for stage in schedule.stages if stage.parent_id}

    for stage in schedule.stages:
        if stage.stage_id in children:
            # У укрупнённой работы своего факта нет — он складывается из потомков.
            continue

        observations = _confirmed_observations(stage, today, site=site)
        compliance = _compliance(observations)
        item = StageProgress(
            stage_id=stage.stage_id,
            state=NOT_STARTED,
            observation_count=len(observations),
            compliance_percent=round(compliance * 100, 1) if compliance is not None else None,
        )

        if today < stage.start_date:
            item.reason = "Плановое начало ещё не наступило; наличие техники не подтверждает начало работ."
        elif today <= stage.end_date:
            item.state = IN_PROGRESS
            item.reason = (
                "Идёт плановый период этапа. Физический прогресс и завершение не подтверждены. "
                "Доля проверок без отклонений характеризует ресурсное соответствие и не переводится в дни задержки."
            )
        else:
            item.state = UNVERIFIED
            item.reason = (
                f"Плановый срок истёк {stage.end_date:%d.%m.%Y}. Завершение и фактическое "
                "отставание не подтверждены: снимки техники не измеряют выполненные объёмы. "
                "Требуется подтверждение ответственного лица или измерение физических объёмов."
            )

        finish, item.estimate_kind, item.completion_confirmed = estimate_finish(stage, today)
        if item.estimate_kind != "plan_reference_scenario":
            item.delay_days = (finish - stage.end_date).days
            if item.completion_confirmed:
                item.state = DONE_ON_TIME if finish <= stage.end_date else OVERDUE
                item.reason = f"Завершение подтверждено ответственным лицом {finish:%d.%m.%Y}: {stage.verified_progress_note}"
            else:
                item.state = (OVERDUE if stage.verified_progress_date > stage.end_date else UNVERIFIED) if today > stage.end_date else IN_PROGRESS
                basis = "Оценка ответственного лица" if item.estimate_kind == "responsible_person_estimate" else "Сценарий сохранения среднего темпа физических работ с планового начала"
                item.reason = f"{basis}: окончание {finish:%d.%m.%Y}. Замер {stage.verified_progress_date:%d.%m.%Y}, готовность {stage.verified_progress_percent}%. Основание: {stage.verified_progress_note}. Это оценка, требуется актуализация при изменении условий."

        progress[stage.stage_id] = item

    return progress


def _ordered_stages(schedule: Schedule) -> list[Stage]:
    """Работы в порядке обхода дерева: раздел, затем его содержимое.

    Без этого клиент получил бы плоский список, отсортированный по дате, где
    вложенная работа стоит выше своего раздела — отступы в таблице выглядели бы
    случайными. Сортировка здесь, а не на клиенте, чтобы порядок был один и тот
    же во всех потребителях API.
    """
    children: dict[str | None, list[Stage]] = {}
    known = {stage.stage_id for stage in schedule.stages}
    for stage in schedule.stages:
        parent = stage.parent_id if stage.parent_id in known else None
        children.setdefault(parent, []).append(stage)
    for group in children.values():
        group.sort(key=lambda s: (s.start_date, s.work_name))

    ordered: list[Stage] = []
    visited: set[str] = set()

    def walk(parent: str | None) -> None:
        for stage in children.get(parent, []):
            if stage.stage_id in visited:
                continue
            visited.add(stage.stage_id)
            ordered.append(stage)
            walk(stage.stage_id)

    walk(None)
    # Работы, потерявшие родителя из-за цикла в иерархии, всё равно должны попасть в ответ.
    ordered.extend(stage for stage in schedule.stages if stage.stage_id not in visited)
    return ordered


def build_report(schedule: Schedule, today: date, site=None) -> NetworkReport:
    """Полный отчёт по сетевому графику: план, факт и сдвиг даты сдачи."""
    network = build_network(schedule)
    baseline = critical_path.compute(network)
    if not baseline.available:
        return NetworkReport(available=False, reason=baseline.reason, cycle=baseline.cycle)

    progress = estimate_progress(schedule, today, site=site)
    delays = {item.stage_id: item.delay_days for item in progress.values() if item.delay_days}
    start_overrides = {
        item.stage_id: item.actual_start for item in progress.values() if item.actual_start
    }
    projected = critical_path.compute(network, delays=delays, start_overrides=start_overrides)
    if not projected.available:
        return NetworkReport(available=False, reason=projected.reason, cycle=projected.cycle)

    shift_days = (projected.project_finish - baseline.project_finish).days
    if shift_days > 0:
        status = BEHIND
    elif shift_days < 0:
        status = AHEAD
    else:
        status = ON_TRACK

    stages_payload = []
    for stage in _ordered_stages(schedule):
        base = baseline.schedules.get(stage.stage_id)
        fact = projected.schedules.get(stage.stage_id)
        if base is None or fact is None:
            continue
        item = progress.get(stage.stage_id)
        stages_payload.append(
            {
                "stage_id": stage.stage_id,
                "work_code": stage.work_code,
                "work_name": stage.work_name,
                "zone_id": stage.zone_id,
                "parent_id": stage.parent_id,
                "predecessor_ids": list(stage.predecessor_ids),
                "level": base.level,
                "is_summary": base.is_summary,
                "planned_start_date": stage.start_date.isoformat(),
                "planned_end_date": stage.end_date.isoformat(),
                "duration_days": base.duration_days,
                "early_start_date": base.early_start.isoformat(),
                "early_finish_date": base.early_finish.isoformat(),
                "late_start_date": base.late_start.isoformat(),
                "late_finish_date": base.late_finish.isoformat(),
                "total_float_days": base.total_float_days,
                "is_critical": base.is_critical,
                "projected_finish_date": fact.early_finish.isoformat(),
                "estimate_kind": item.estimate_kind if item else "summary",
                "physical_progress_percent": stage.verified_progress_percent,
                "verified_progress_date": stage.verified_progress_date.isoformat() if stage.verified_progress_date else None,
                "verified_progress_note": stage.verified_progress_note,
                "completion_confirmed": item.completion_confirmed if item else False,
                "completion_basis": "responsible_person_record" if item and item.completion_confirmed else "not_recorded",
                "state": item.state if item else "",
                "state_label_ru": ("Завершён с опозданием" if item.completion_confirmed and item.state == OVERDUE else STATE_LABELS.get(item.state, "")) if item else "",
                "delay_days": item.delay_days if item else 0,
                "observation_count": item.observation_count if item else 0,
                "compliance_percent": item.compliance_percent if item else None,
                "reason": item.reason if item else "",
                # Отставание на критическом пути двигает сдачу объекта, отставание
                # внутри запаса — нет. Это и есть разница в важности отклонения.
                "shifts_project_finish": bool(
                    item and item.delay_days and item.delay_days > base.total_float_days
                ),
            }
        )

    return NetworkReport(
        available=True,
        baseline_finish=baseline.project_finish,
        projected_finish=projected.project_finish,
        shift_days=shift_days,
        status=status,
        stages=stages_payload,
        critical_stage_ids=baseline.critical_stage_ids,
        unverified_stage_ids=[
            item.stage_id for item in progress.values() if item.state == UNVERIFIED
        ],
    )


def to_dict(report: NetworkReport) -> dict:
    return {
        "estimate_kind": "physical_progress_scenario" if any(s.get("estimate_kind") not in ("plan_reference_scenario", "summary") for s in report.stages) else "plan_reference_scenario",
        "uncertainty": "scenario_requires_updates",
        "estimate_basis": "Датированные замеры физических объёмов и ожидаемые даты ответственного; при отсутствии замеров — календарный план. Сдвиги распространяются по технологическим связям с учётом резерва.",
        "available": report.available,
        "reason": report.reason,
        "cycle": report.cycle,
        "baseline_finish_date": report.baseline_finish.isoformat() if report.baseline_finish else None,
        "projected_finish_date": (
            report.projected_finish.isoformat() if report.projected_finish else None
        ),
        "shift_days": report.shift_days,
        "status": report.status,
        "status_label_ru": ("Сценарий без сдвига" if report.status == ON_TRACK and any(s.get("estimate_kind") not in ("plan_reference_scenario", "summary") for s in report.stages) else PROJECT_STATUS_LABELS.get(report.status, "")),
        "stages": report.stages,
        "critical_stage_ids": report.critical_stage_ids,
        "unverified_stage_ids": report.unverified_stage_ids,
    }


def critical_stage_ids(schedule: Schedule) -> set[str]:
    """Идентификаторы работ на критическом пути — без обращения к истории.

    Нужно там, где важна только повышенная значимость отклонения по этапу:
    проверка снимка не должна ради этого поднимать всю историю наблюдений.
    """
    result = critical_path.compute(build_network(schedule))
    return set(result.critical_stage_ids) if result.available else set()
