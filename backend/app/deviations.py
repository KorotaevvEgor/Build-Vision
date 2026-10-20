"""Формирование предупреждений и история их обработки.

Повторная находка обновляет существующее отклонение. Пригодный контрольный
снимок сохраняет результат проверки, но не закрывает обращение автоматически.
Независимость наблюдений проверяет evidence.py; закрытие и инженерная проверка
учитываются отдельно от числа визуальных подтверждений.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from . import django_bridge

logger = logging.getLogger(__name__)

#: Типы отклонений, которые нельзя закрыть снимком другой зоны или кадром вообще:
#: они говорят о настройке системы, а не о происходящем в кадре.
_NOT_FRAME_SCOPED = {"zone_not_covered"}


class Finding:
    """Одна находка по снимку до превращения её в запись отклонения."""

    __slots__ = ("equipment", "kind", "message", "severity", "signature", "stage_id", "title")

    def __init__(
        self,
        *,
        kind: str,
        severity: str,
        title: str,
        message: str,
        equipment: list[str] | None = None,
        stage_id: str | None = None,
        signature_extra: str = "",
    ) -> None:
        self.kind = kind
        self.severity = severity
        self.title = title
        self.message = message
        self.equipment = equipment or []
        self.stage_id = stage_id
        # Ключ намеренно не включает дату и номер снимка: одно и то же нарушение
        # на разных кадрах обязано совпасть. Но включает состав техники — нехватка
        # экскаватора и нехватка самосвала это разные нарушения одного этапа.
        self.signature = "|".join(
            [kind, stage_id or "-", signature_extra or ",".join(sorted(self.equipment))]
        )


def _severity_for_stage(is_critical: bool, base: str) -> str:
    """Отклонение на критическом пути важнее такого же с запасом времени."""
    if is_critical and base == "warning":
        return "critical"
    return base


def findings_from_evaluation(evaluation, *, critical_stage_ids: set[str] | None = None) -> list[Finding]:
    """Находки из результата проверки по правилам техники."""
    critical_stage_ids = critical_stage_ids or set()
    findings: list[Finding] = []

    for item in evaluation.stage_evaluations:
        if item.status == 'insufficient_data':
            continue
        critical = item.stage_id in critical_stage_ids
        # Подписи требуемых классов берутся из quantity_checks (они там есть даже при
        # нулевом факте, см. matching.py::_evaluate_stage) — иначе в титул/сообщении
        # отклонения утекает сырой английский class_key.
        labels_by_class = {c.class_key: c.label_ru for c in item.quantity_checks}

        if item.missing_required:
            missing_labels = sorted(labels_by_class.get(k, k) for k in item.missing_required)
            names = ", ".join(missing_labels)
            findings.append(
                Finding(
                    kind="missing_equipment",
                    severity=_severity_for_stage(critical, "warning"),
                    title=f"Нет требуемой техники: {item.work_name}",
                    message=(
                        f"На этапе «{item.work_name}» не обнаружена требуемая техника: {names}. "
                        + item.explanation_ru
                    ),
                    equipment=missing_labels,
                    stage_id=item.stage_id,
                )
            )

        shortfalls = [c for c in item.quantity_checks if not c.satisfied and c.class_key not in item.missing_required]
        if shortfalls:
            names = ", ".join(
                f"{c.label_ru} (план {c.required_qty}, факт {c.actual_qty})" for c in shortfalls
            )
            findings.append(
                Finding(
                    kind="quantity_shortfall",
                    severity=_severity_for_stage(critical, "warning"),
                    title=f"Техники меньше плана: {item.work_name}",
                    message=f"На этапе «{item.work_name}» техники меньше планового количества: {names}.",
                    equipment=[c.label_ru for c in shortfalls],
                    stage_id=item.stage_id,
                )
            )

        unexpected = sorted({d.label_ru for d in item.unexpected_detections})
        if unexpected:
            findings.append(
                Finding(
                    kind="unexpected_equipment",
                    severity="info",
                    title=f"Посторонняя техника: {item.work_name}",
                    message=(
                        "Обнаружена техника вне разрешённого набора работ зоны: "
                        f"{', '.join(unexpected)}. Проверьте, не связана ли она с параллельными работами."
                    ),
                    equipment=unexpected,
                    stage_id=item.stage_id,
                )
            )

    for finding in findings:
        evaluated = next((e for e in evaluation.stage_evaluations if e.stage_id == finding.stage_id), None)
        fingerprint = evaluated.methodology.get('rule_fingerprint') if evaluated else None
        if fingerprint:
            finding.signature += '|' + fingerprint[:16]
    return findings


def findings_from_ai(ai_block: dict, *, stage_id: str | None = None) -> list[Finding]:
    """Находки из блока обогащения: зоны кадра, простой, расхождение стадии."""
    findings: list[Finding] = []
    for item in (ai_block or {}).get("zone_deviations") or []:
        findings.append(
            Finding(
                kind=item["kind"],
                severity=item["severity"],
                title=item["title"],
                message=item["message"],
                equipment=item.get("equipment") or [],
                # Непокрытая зона относится к настройке камер, а не к этапу.
                stage_id=None if item["kind"] in _NOT_FRAME_SCOPED else stage_id,
            )
        )

    mismatch = (ai_block or {}).get("stage_mismatch")
    if mismatch:
        findings.append(
            Finding(
                kind="stage_mismatch",
                severity="warning",
                title="Стадия на снимке не совпадает с графиком",
                message=mismatch["message"],
                stage_id=stage_id,
                signature_extra=mismatch["observed_stage"],
            )
        )
    return findings


def sync_from_observation(
    *,
    observation_id,
    zone_external_id: str,
    site,
    findings: list[Finding],
    observation_status: str,
    critical_stage_ids: set[str] | None = None,
) -> dict:
    """Сводит находки снимка с открытыми отклонениями зоны.

    Возвращает сводку для ответа API: что открыто, что повторилось, что
    закрылось само. Никогда не роняет анализ снимка — при проблеме с БД
    возвращает пустую сводку с признаком недоступности.
    """
    if not django_bridge.ensure_django_ready():
        return {"available": False, "opened": [], "repeated": [], "auto_resolved": []}

    try:
        return _sync(
            observation_id=observation_id,
            zone_external_id=zone_external_id,
            site=site,
            findings=findings,
            observation_status=observation_status,
            critical_stage_ids=critical_stage_ids or set(),
        )
    except Exception:
        logger.exception("Не удалось синхронизировать отклонения по наблюдению %s", observation_id)
        return {"available": False, "opened": [], "repeated": [], "auto_resolved": []}


def _sync(
    *,
    observation_id,
    zone_external_id: str,
    site,
    findings: list[Finding],
    observation_status: str,
    critical_stage_ids: set[str],
) -> dict:
    from django.db import connection, transaction

    from core.models import Deviation, Observation, ProjectEvent, Stage, Zone

    zone = Zone.objects.filter(external_id=zone_external_id, **({"site":site} if site is not None else {"site__is_legacy":True})).first()
    observation = Observation.objects.filter(pk=observation_id).first()
    if zone is None or observation is None or observation.zone_id != zone.pk:
        return {"available": False, "opened": [], "repeated": [], "auto_resolved": []}

    project = site if site is not None else zone.site
    stages_by_id = {
        s.external_id: s for s in Stage.objects.filter(external_id__in={f.stage_id for f in findings if f.stage_id})
    }

    opened: list[dict] = []
    repeated: list[dict] = []
    auto_resolved: list[dict] = []
    now = datetime.now(UTC)

    with transaction.atomic():
        if connection.features.has_select_for_update:
            # Lock a row that exists even before the first alert is created.
            Zone.objects.select_for_update().get(pk=zone.pk)
        open_qs = Deviation.objects.filter(zone=zone, status__in=Deviation.OPEN_STATUSES)
        # Блокировка строк нужна на Postgres, где два снимка одной зоны могут
        # обрабатываться параллельно и создать дубликаты. SQLite её не поддерживает и
        # выбросил бы исключение, поэтому спрашиваем возможности бэкенда, а не имя СУБД.
        if connection.features.has_select_for_update:
            open_qs = open_qs.select_for_update()
        open_deviations = {item.signature: item for item in open_qs}

        for finding in findings:
            stage = stages_by_id.get(finding.stage_id) if finding.stage_id else None
            existing = open_deviations.get(finding.signature)
            if existing is not None:
                existing.last_observation = observation
                from .evidence import record_evidence
                already_recorded = existing.evidence_records.filter(observation=observation).exists()
                proof = record_evidence(existing, observation, present=True, observation_status=observation_status)
                # Journal occurrences and independent proof are deliberately different counters.
                existing.occurrence_count += int(not already_recorded)
                existing.message = finding.message
                existing.severity = finding.severity
                existing.save(
                    update_fields=[
                        "last_observation",
                        "occurrence_count",
                        "message",
                        "severity",
                        "updated_at",
                    ]
                )
                ProjectEvent.objects.create(
                    site=project,
                    kind=ProjectEvent.Kind.DEVIATION_REPEATED,
                    title=existing.title,
                    message=(
                        f"Повторная проверка: {proof.reason}. Независимая серия: {proof.sequence_count}."
                    ),
                    zone=zone,
                    observation=observation,
                    deviation=existing,
                )
                repeated.append({"id": existing.pk, "title": existing.title})
                continue

            deviation = Deviation.objects.create(
                zone=zone,
                stage=stage,
                kind=finding.kind,
                severity=finding.severity,
                status=Deviation.Status.DETECTED,
                signature=finding.signature,
                title=finding.title,
                message=finding.message,
                equipment=finding.equipment,
                is_on_critical_path=bool(finding.stage_id and finding.stage_id in critical_stage_ids),
                first_observation=observation,
                last_observation=observation,
            )
            ProjectEvent.objects.create(
                site=project,
                kind=ProjectEvent.Kind.DEVIATION_DETECTED,
                title=deviation.title,
                message=deviation.message,
                new_value=deviation.get_status_display(),
                zone=zone,
                observation=observation,
                deviation=deviation,
            )
            from .evidence import record_evidence
            record_evidence(deviation, observation, present=True, observation_status=observation_status)
            opened.append({"id": deviation.pk, "title": deviation.title})

        # A clean frame is evidence, not an engineering decision to close the issue.
        current_signatures = {f.signature for f in findings}
        from .evidence import record_evidence
        for signature, deviation in open_deviations.items():
            if signature not in current_signatures and deviation.kind not in _NOT_FRAME_SCOPED:
                proof = record_evidence(deviation, observation, present=False, observation_status=observation_status)
                if proof.independent:
                    ProjectEvent.objects.create(site=project, kind=ProjectEvent.Kind.OBSERVATION_ANALYZED,
                        title='Контрольная проверка отклонения', message=proof.reason + '. Автоматическое закрытие не выполняется.',
                        zone=zone, observation=observation, deviation=deviation)

        ProjectEvent.objects.create(
            site=project,
            kind=ProjectEvent.Kind.OBSERVATION_ANALYZED,
            title=f"Снимок зоны «{zone.name}» проанализирован",
            message=(
                f"Выявлено новых отклонений: {len(opened)}, повторились: {len(repeated)}, "
                f"закрыто по факту следующего снимка: {len(auto_resolved)}."
            ),
            zone=zone,
            observation=observation,
        )

    return {
        "available": True,
        "opened": opened,
        "repeated": repeated,
        "auto_resolved": auto_resolved,
    }


def _deviation_to_dict(item) -> dict:
    from .evidence import proof_summary
    return {
        "proof": proof_summary(item),
        "engineering_review": item.engineering_review,
        "id": item.pk,
        "kind": item.kind,
        "kind_label_ru": item.get_kind_display(),
        "severity": item.severity,
        "severity_label_ru": item.get_severity_display(),
        "status": item.status,
        "status_label_ru": item.get_status_display(),
        "title": item.title,
        "message": item.message,
        "equipment": item.equipment,
        "zone_id": item.zone.external_id,
        "zone_name": item.zone.name,
        "stage_id": item.stage.external_id if item.stage else None,
        "work_name": item.stage.work_name if item.stage else None,
        "is_on_critical_path": item.is_on_critical_path,
        "occurrence_count": item.occurrence_count,
        "auto_resolved": item.auto_resolved,
        "resolution_note": item.resolution_note,
        "assignee": item.assignee.get_full_name() or item.assignee.username if item.assignee else None,
        "assignee_id": item.assignee_id,
        "before_observation_id": str(item.first_observation_id) if item.first_observation_id else None,
        "after_observation_id": (
            str(item.resolved_observation_id) if item.resolved_observation_id else None
        ),
        "detected_at": item.detected_at.isoformat(),
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
        "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
    }


def list_deviations(*, site, status: str | None = None, limit: int = 100) -> dict:
    if not django_bridge.ensure_django_ready():
        return {"available": False, "items": [], "counts": {}}
    from core.models import Deviation

    site_filter = {"zone__site": site} if site is not None else {"zone__site__is_legacy": True}
    from django.db.models import Prefetch
    from core.models import DeviationEvidence
    qs = Deviation.objects.filter(**site_filter).select_related("zone", "stage", "assignee").prefetch_related(
        Prefetch('evidence_records', queryset=DeviationEvidence.objects.select_related('observation').defer(
            'methodology_snapshot','observation__analysis_history','observation__ai_analysis','observation__overall_explanation')))
    counts = {key: 0 for key, _ in Deviation.Status.choices}
    for value in qs.values_list("status", flat=True):
        counts[value] = counts.get(value, 0) + 1
    if status:
        qs = qs.filter(status=status)
    # Критичное и на критическом пути — выше: инженер должен видеть это первым.
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    items = sorted(
        qs[:limit],
        key=lambda d: (severity_order.get(d.severity, 3), not d.is_on_critical_path, -d.pk),
    )
    return {
        "available": True,
        "items": [_deviation_to_dict(item) for item in items],
        "counts": counts,
        "statuses": [{"key": k, "label_ru": v} for k, v in Deviation.Status.choices],
    }


def get_deviation(*, deviation_id: int, site) -> dict | None:
    """Project-scoped evidence. Quantities come from the original stage check, never prose."""
    if not django_bridge.ensure_django_ready():
        return None
    from core.models import Deviation, ProjectEvent

    item = Deviation.objects.filter(pk=deviation_id, zone__site=site).select_related(
        "zone", "stage", "assignee", "first_observation__camera", "last_observation__camera", "resolved_observation__camera"
    ).prefetch_related('evidence_records__observation', 'first_observation__detections',
                       'last_observation__detections', 'resolved_observation__detections').first()
    if item is None:
        return None
    checks = []
    methodology = {}
    if item.first_observation and item.first_observation.zone_id == item.zone_id and item.stage_id:
        evaluation = item.first_observation.stage_evaluations.filter(stage_id=item.stage_id).first()
        if evaluation:
            methodology = evaluation.methodology_snapshot
            checks = [c for c in evaluation.quantity_checks_snapshot
                      if not c.get("satisfied") and (not item.equipment or
                         c.get("class_key") in item.equipment or c.get("label_ru") in item.equipment)]
    first_proof = item.evidence_records.order_by('pk').first()
    if first_proof and first_proof.methodology_snapshot:
        methodology = first_proof.methodology_snapshot
        checks = [c for c in methodology.get('quantity_checks', []) if not c.get('satisfied') and
            (not item.equipment or c.get('class_key') in item.equipment or c.get('label_ru') in item.equipment)]
    evidence, seen = [], set()
    for label, observation in [("Выявлено", item.first_observation),
                               ("Последняя фиксация", item.last_observation),
                               ("Проверка устранения", item.resolved_observation)]:
        if observation and observation.pk not in seen and observation.zone_id == item.zone_id:
            seen.add(observation.pk)
            evidence.append({"observation_id": str(observation.pk), "label": label,
                "observed_date": observation.observed_date.isoformat() if observation.observed_date else None,
                "date_confirmed": observation.date_confirmed, "created_at": observation.created_at.isoformat(),
                "image_width": observation.image_width, "image_height": observation.image_height,
                "camera_id": observation.camera.external_id if observation.camera and observation.camera.zone_id == item.zone_id else None,
                "camera_name": observation.camera.name if observation.camera and observation.camera.zone_id == item.zone_id else None,
                # These are the observation's saved detections, not a reconstruction of
                # historical methodology (which can predate a reanalysis).
                "captured_at": observation.captured_at.isoformat() if observation.captured_at else None,
                "detections_source": "observation",
                "detections": [{"id": d.pk, "class_key": d.class_key, "label_ru": d.label_ru,
                    "confidence": d.confidence, "bbox": d.bbox, "ambiguous": d.ambiguous,
                    "activity": d.activity, "activity_reason": d.activity_reason}
                    for d in observation.detections.all()]})
    events = ProjectEvent.objects.filter(site=site, deviation=item).select_related("actor").order_by("-created_at")[:30]
    return {"deviation": _deviation_to_dict(item), "quantity_checks": checks, "evidence": evidence, "methodology": methodology,
        "events": [{"id": e.pk, "title": e.title, "kind_label_ru": e.get_kind_display(),
                    "created_at": e.created_at.isoformat(), "message": e.message,
                    "old_value": e.old_value, "new_value": e.new_value,
                    "actor": e.actor.get_full_name() or e.actor.username if e.actor else None} for e in events]}


def change_status(*, deviation_id: int, site, status: str, user_id: int, assignee_id: int | None, note: str) -> dict | None:
    """Переводит отклонение в новое состояние и пишет событие в журнал."""
    if not django_bridge.ensure_django_ready():
        return None
    from core.models import Deviation, ProjectEvent

    site_filter = {"zone__site": site} if site is not None else {"zone__site__is_legacy": True}
    item = (
        Deviation.objects.filter(pk=deviation_id, **site_filter)
        .select_related("zone", "stage", "assignee")
        .first()
    )
    if item is None:
        return None

    previous = item.get_status_display()
    now = datetime.now(UTC)
    item.status = status
    if assignee_id is not None:
        item.assignee_id = assignee_id
    if note:
        item.resolution_note = note
    if status == Deviation.Status.RESOLVED:
        item.resolved_at = item.resolved_at or now
        # Ручное закрытие — не автоматическое, и путать их в отчёте нельзя.
        item.auto_resolved = False
    if status == Deviation.Status.CONFIRMED:
        item.confirmed_at = now
    item.save()

    ProjectEvent.objects.create(
        site=item.zone.site,
        kind=ProjectEvent.Kind.DEVIATION_STATUS_CHANGED,
        title=item.title,
        message=note,
        old_value=previous,
        new_value=item.get_status_display(),
        zone=item.zone,
        deviation=item,
        actor_id=user_id,
    )
    return _deviation_to_dict(item)


def list_events(*, site, limit: int = 50) -> dict:
    if not django_bridge.ensure_django_ready():
        return {"available": False, "items": []}
    from core.models import ProjectEvent

    site_filter = {"site": site} if site is not None else {"site__is_legacy": True}
    qs = (
        ProjectEvent.objects.filter(**site_filter)
        .select_related("zone", "deviation", "actor")
        .order_by("-created_at")[:limit]
    )
    return {
        "available": True,
        "items": [
            {
                "id": event.pk,
                "kind": event.kind,
                "kind_label_ru": event.get_kind_display(),
                "title": event.title,
                "message": event.message,
                "old_value": event.old_value,
                "new_value": event.new_value,
                "zone_name": event.zone.name if event.zone else None,
                "observation_id": str(event.observation_id) if event.observation_id else None,
                "deviation_id": event.deviation_id,
                "actor": (event.actor.get_full_name() or event.actor.username) if event.actor else None,
                "created_at": event.created_at.isoformat(),
            }
            for event in qs
        ],
    }
