"""Метод критического пути над сетевым графиком работ.

Зачем это нужно именно здесь. Плоский список этапов отвечает только на
вопрос «идёт ли работа по своим датам». Стройку интересует другое: сдвинет
ли отставание по конкретной работе дату сдачи объекта. Ответ даёт запас
времени (total float): если он нулевой, работа лежит на критическом пути и
каждый потерянный день переносит сдачу; если запас есть, отставание внутри
него ничего не двигает и не должно поднимать тревогу наравне с критическим.

Модуль намеренно не знает ни про Django, ни про API: на вход — простые
структуры, на выход — расчёт. Это единственный способ покрыть его тестами,
не поднимая базу.

Принятые допущения, которые обязаны быть в документации:

* связь только «окончание-начало» без задержек (finish-to-start, lag 0) —
  в исходных материалах заказчика других типов связей нет;
* длительность считается в календарных днях, включая обе границы, потому
  что производственный календарь заказчика нам не передавали;
* расчёт идёт по листовым работам; укрупнённая работа получает сроки
  своих потомков и критична, если критичен хотя бы один потомок;
* связь, указанная на укрупнённую работу, раскрывается на все её листья —
  иначе зависимость от раздела пришлось бы дублировать руками.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

DAY = timedelta(days=1)


@dataclass(frozen=True)
class NetworkStage:
    """Вход расчёта: одна работа графика."""

    stage_id: str
    work_name: str
    zone_id: str
    start_date: date
    end_date: date
    parent_id: str | None = None
    predecessor_ids: tuple[str, ...] = ()
    work_code: str = ""


@dataclass
class StageSchedule:
    """Результат расчёта по одной работе."""

    stage_id: str
    early_start: date
    early_finish: date
    late_start: date
    late_finish: date
    total_float_days: int
    is_critical: bool
    is_summary: bool
    level: int
    duration_days: int
    #: Насколько ранний старт сдвинут относительно плановой даты начала.
    #: Положительное значение означает, что предшественники не дают начать вовремя.
    start_shift_days: int = 0


@dataclass
class NetworkResult:
    available: bool
    reason: str = ""
    #: Работы, образующие цикл связей. Пока цикл не разорван, расчёт невозможен.
    cycle: list[str] = field(default_factory=list)
    schedules: dict[str, StageSchedule] = field(default_factory=dict)
    project_finish: date | None = None
    critical_stage_ids: list[str] = field(default_factory=list)


def _duration(stage: NetworkStage) -> int:
    """Длительность в календарных днях, включая день начала и день окончания."""
    return max((stage.end_date - stage.start_date).days + 1, 1)


def _level(stage_id: str, parents: dict[str, str | None]) -> int:
    """Глубина вложенности работы. Цикл в иерархии не вешает расчёт."""
    level = 0
    seen: set[str] = set()
    current = parents.get(stage_id)
    while current is not None and current not in seen:
        seen.add(current)
        level += 1
        current = parents.get(current)
    return level


def _leaf_descendants(stage_id: str, children: dict[str, list[str]]) -> list[str]:
    """Все листовые потомки работы; для самого листа — он сам."""
    direct = children.get(stage_id)
    if not direct:
        return [stage_id]
    result: list[str] = []
    for child in direct:
        result.extend(_leaf_descendants(child, children))
    return result


def _topological_order(nodes: list[str], edges: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    """Порядок обхода и, если сортировка невозможна, работы из цикла.

    Алгоритм Кана: узлы без входящих связей уходят в результат, остаток —
    это в точности те работы, что замкнуты в цикл. Возвращать их важнее, чем
    просто сообщить об ошибке: пользователю нужно знать, какую связь убрать.
    """
    incoming = {node: set(edges.get(node, set())) for node in nodes}
    ready = sorted(node for node, preds in incoming.items() if not preds)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for other, preds in incoming.items():
            if node in preds:
                preds.discard(node)
                if not preds and other not in order and other not in ready:
                    ready.append(other)
        ready.sort()
    if len(order) != len(nodes):
        return order, sorted(set(nodes) - set(order))
    return order, []


def compute(
    stages: list[NetworkStage],
    *,
    delays: dict[str, int] | None = None,
    start_overrides: dict[str, date] | None = None,
) -> NetworkResult:
    """Считает ранние и поздние сроки, запас и критический путь.

    ``delays`` продлевает длительность конкретных работ на указанное число
    дней. Это и есть механизм «сдвига даты сдачи»: тот же расчёт с фактическим
    отставанием на входе даёт прогнозную дату окончания проекта.

    ``start_overrides`` заменяет плановую дату начала фактической. Без него
    опережение в принципе невыразимо: плановая дата работает как ограничение
    «не раньше чем», и досрочно начатая работа ничего бы не сдвинула.
    """
    if not stages:
        return NetworkResult(available=False, reason="В графике нет ни одного этапа")

    delays = delays or {}
    start_overrides = start_overrides or {}
    by_id = {stage.stage_id: stage for stage in stages}
    parents = {stage.stage_id: stage.parent_id for stage in stages}
    children: dict[str, list[str]] = {}
    for stage in stages:
        if stage.parent_id and stage.parent_id in by_id:
            children.setdefault(stage.parent_id, []).append(stage.stage_id)

    leaves = [stage.stage_id for stage in stages if stage.stage_id not in children]

    # Связь на укрупнённую работу означает зависимость от всех её листьев.
    leaf_predecessors: dict[str, set[str]] = {}
    for leaf in leaves:
        resolved: set[str] = set()
        for predecessor in by_id[leaf].predecessor_ids:
            if predecessor not in by_id or predecessor == leaf:
                continue
            resolved.update(_leaf_descendants(predecessor, children))
        resolved.discard(leaf)
        leaf_predecessors[leaf] = resolved

    order, cycle = _topological_order(leaves, leaf_predecessors)
    if cycle:
        return NetworkResult(
            available=False,
            reason="Связи предшествования образуют цикл — расчёт критического пути невозможен",
            cycle=cycle,
        )

    durations = {leaf: max(1, _duration(by_id[leaf]) + delays.get(leaf, 0)) for leaf in leaves}

    early_start: dict[str, date] = {}
    early_finish: dict[str, date] = {}
    for leaf in order:
        earliest = start_overrides.get(leaf, by_id[leaf].start_date)
        for predecessor in leaf_predecessors[leaf]:
            candidate = early_finish[predecessor] + DAY
            earliest = max(earliest, candidate)
        early_start[leaf] = earliest
        early_finish[leaf] = earliest + timedelta(days=durations[leaf] - 1)

    project_finish = max(early_finish.values())

    successors: dict[str, set[str]] = {leaf: set() for leaf in leaves}
    for leaf, preds in leaf_predecessors.items():
        for predecessor in preds:
            successors[predecessor].add(leaf)

    late_finish: dict[str, date] = {}
    late_start: dict[str, date] = {}
    for leaf in reversed(order):
        if successors[leaf]:
            latest = min(late_start[s] - DAY for s in successors[leaf])
        else:
            latest = project_finish
        late_finish[leaf] = latest
        late_start[leaf] = latest - timedelta(days=durations[leaf] - 1)

    schedules: dict[str, StageSchedule] = {}
    for leaf in leaves:
        total_float = (late_start[leaf] - early_start[leaf]).days
        schedules[leaf] = StageSchedule(
            stage_id=leaf,
            early_start=early_start[leaf],
            early_finish=early_finish[leaf],
            late_start=late_start[leaf],
            late_finish=late_finish[leaf],
            total_float_days=total_float,
            is_critical=total_float <= 0,
            is_summary=False,
            level=_level(leaf, parents),
            duration_days=durations[leaf],
            start_shift_days=(early_start[leaf] - by_id[leaf].start_date).days,
        )

    # Укрупнённые работы получают границы своих потомков: отдельных сроков у
    # раздела нет, он ровно настолько длинный, насколько его содержимое.
    for stage in stages:
        if stage.stage_id in schedules:
            continue
        descendants = [d for d in _leaf_descendants(stage.stage_id, children) if d in schedules]
        if not descendants:
            continue
        parts = [schedules[d] for d in descendants]
        summary_float = min(p.total_float_days for p in parts)
        schedules[stage.stage_id] = StageSchedule(
            stage_id=stage.stage_id,
            early_start=min(p.early_start for p in parts),
            early_finish=max(p.early_finish for p in parts),
            late_start=min(p.late_start for p in parts),
            late_finish=max(p.late_finish for p in parts),
            total_float_days=summary_float,
            is_critical=any(p.is_critical for p in parts),
            is_summary=True,
            level=_level(stage.stage_id, parents),
            duration_days=sum(p.duration_days for p in parts),
            start_shift_days=max(p.start_shift_days for p in parts),
        )

    return NetworkResult(
        available=True,
        schedules=schedules,
        project_finish=project_finish,
        critical_stage_ids=sorted(
            stage_id
            for stage_id, item in schedules.items()
            if item.is_critical and not item.is_summary
        ),
    )
