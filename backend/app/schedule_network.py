"""Сетевой график проекта: план, факт по фотоконтролю и сдвиг даты сдачи.

Здесь соединяются две вещи, которые по отдельности бесполезны. Расчёт
критического пути (`critical_path.py`) знает про связи работ, но ничего не
знает про стройку. История наблюдений знает, что происходило на площадке, но
не знает, чем это грозит сроку сдачи. Модуль переводит второе в первое:
оценивает отставание по каждой работе и прогоняет тот же расчёт повторно с
этим отставанием на входе.

Честность оценки важнее её точности, поэтому каждая работа получает не только
число дней, но и состояние с формулировкой, откуда это число взялось.
Отдельно выделено состояние «срок истёк, подтверждающих снимков нет»: это не
отставание и не выполнение, это отсутствие контроля, и путать его с
благополучием нельзя.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import critical_path, django_bridge
from .schedule import Schedule, Stage

#: Состояния работы по фактическим данным фотоконтроля.
NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
DONE_ON_TIME = "done_on_time"
OVERDUE = "overdue"
UNVERIFIED = "unverified"
STARTED_EARLY = "started_early"

STATE_LABELS = {
    NOT_STARTED: "Не начат",
    IN_PROGRESS: "Идёт",
    DONE_ON_TIME: "Завершён в срок",
    OVERDUE: "Просрочен",
    UNVERIFIED: "Срок истёк, контроль не подтверждён",
    STARTED_EARLY: "Начат досрочно",
}

BEHIND = "behind"
ON_TRACK = "on_track"
AHEAD = "ahead"

PROJECT_STATUS_LABELS = {
    BEHIND: "Отставание от графика",
    ON_TRACK: "В графике",
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


def _required_class_keys(stage_id: str) -> set[str]:
    if not django_bridge.ensure_django_ready():
        return set()
    from core.models import StageRequiredItem

    return set(
        StageRequiredItem.objects.filter(stage_rule__stage__external_id=stage_id).values_list(
            "vocabulary_class__key", flat=True
        )
    )


def _detected_early_start(stage: Stage, today: date, site=None) -> date | None:
    """Дата, с которой работа фактически идёт, если она началась раньше плана.

    Признак намеренно строгий: до плановой даты начала в зоне должен быть
    подтверждённый снимок, на котором уверенно видна вся обязательная для этой
    работы техника. Одной машины мало — она может оказаться там проездом.
    Без такого признака опережение графика не объявляется вообще: подтвердить
    досрочное выполнение по фотографиям иначе нельзя.
    """
    if today < stage.start_date or not django_bridge.ensure_django_ready():
        return None

    required = _required_class_keys(stage.stage_id)
    if not required:
        return None

    from core.models import Observation

    site_filter = {"zone__site": site} if site is not None else {"zone__site__is_legacy": True}
    candidates = Observation.objects.filter(
        zone__external_id=stage.zone_id,
        observed_date__lt=stage.start_date,
        date_confirmed=True,
        **site_filter,
    ).order_by("observed_date")

    for observation in candidates:
        present = {
            d.class_key
            for d in observation.detections.all()
            if d.in_taxonomy and not d.ambiguous
        }
        if required.issubset(present):
            return observation.observed_date
    return None


def _compliance(observations: list) -> float | None:
    if not observations:
        return None
    return sum(1 for o in observations if o.overall_status == "no_deviation") / len(observations)


def estimate_progress(schedule: Schedule, today: date, site=None) -> dict[str, StageProgress]:
    """Оценивает состояние каждой работы по подтверждённым наблюдениям.

    Оценка темпа — та же эвристика, что в модуле прогноза: доля наблюдений без
    отклонений. Это не измеренный физический прогресс, и так это и должно быть
    описано пользователю.
    """
    progress: dict[str, StageProgress] = {}
    children = {stage.parent_id for stage in schedule.stages if stage.parent_id}

    for stage in schedule.stages:
        if stage.stage_id in children:
            # У укрупнённой работы своего факта нет — он складывается из потомков.
            continue

        observations = _confirmed_observations(stage, today, site=site)
        compliance = _compliance(observations)
        planned_days = (stage.end_date - stage.start_date).days + 1
        item = StageProgress(
            stage_id=stage.stage_id,
            state=NOT_STARTED,
            observation_count=len(observations),
            compliance_percent=round(compliance * 100, 1) if compliance is not None else None,
        )

        if today < stage.start_date:
            early_start = _detected_early_start(stage, today, site=site)
            if early_start is not None:
                item.state = STARTED_EARLY
                item.actual_start = early_start
                item.reason = (
                    f"Работа идёт с {early_start:%d.%m.%Y} — на снимке подтверждена вся "
                    "обязательная техника этапа раньше планового начала."
                )
            else:
                item.reason = "Этап ещё не начался по графику."
        elif stage.start_date <= today <= stage.end_date:
            item.state = IN_PROGRESS
            if compliance is None:
                item.reason = "Этап идёт, подтверждённых снимков за период пока нет."
            elif compliance > 0:
                item.delay_days = max(0, round(planned_days * (1 / compliance - 1)))
                item.reason = (
                    f"По {len(observations)} подтверждённым снимкам доля проверок без отклонений "
                    f"{compliance * 100:.0f}%."
                )
            else:
                item.delay_days = planned_days
                item.reason = (
                    "Ни одна проверка за период этапа не прошла без отклонений — "
                    "оценка отставания грубая, нужен выезд на площадку."
                )
        elif not observations:
            item.state = UNVERIFIED
            item.reason = (
                "Плановый срок истёк, но за период этапа нет ни одного снимка с подтверждённой "
                "датой. Ход работ по этой работе камерами не проверен."
            )
        elif observations[-1].overall_status == "no_deviation":
            item.state = DONE_ON_TIME
            item.reason = (
                f"Последняя проверка {observations[-1].observed_date:%d.%m.%Y} прошла без "
                "отклонений в пределах планового срока."
            )
        else:
            item.state = OVERDUE
            item.delay_days = (today - stage.end_date).days
            item.reason = (
                f"Плановый срок истёк {stage.end_date:%d.%m.%Y}, последняя проверка "
                f"{observations[-1].observed_date:%d.%m.%Y} показала отклонение — работа "
                "считается незавершённой."
            )

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
                "state": item.state if item else "",
                "state_label_ru": STATE_LABELS.get(item.state, "") if item else "",
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
        "available": report.available,
        "reason": report.reason,
        "cycle": report.cycle,
        "baseline_finish_date": report.baseline_finish.isoformat() if report.baseline_finish else None,
        "projected_finish_date": (
            report.projected_finish.isoformat() if report.projected_finish else None
        ),
        "shift_days": report.shift_days,
        "status": report.status,
        "status_label_ru": PROJECT_STATUS_LABELS.get(report.status, ""),
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
