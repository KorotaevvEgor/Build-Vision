"""Bounded, optional AI enrichment. Deterministic observations never wait for it."""
from __future__ import annotations

import logging
import queue
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import observation_ai, zone_deviations

logger = logging.getLogger(__name__)


class BoundedWorker:
    """One worker and a finite waiting room; saturation is explicit backpressure."""
    def __init__(self, capacity=8):
        self.queue = queue.Queue(maxsize=capacity)
        self.lock = threading.Lock()
        self.thread = None

    def submit(self, callback):
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, name="observation-ai", daemon=True)
                self.thread.start()
            try:
                self.queue.put_nowait(callback)
                return True
            except queue.Full:
                return False

    def _run(self):
        while True:
            callback = self.queue.get()
            try:
                callback()
            except Exception:
                logger.exception("Background observation analysis failed")
            finally:
                self.queue.task_done()

    def health(self):
        return {"queued": self.queue.qsize(), "capacity": self.queue.maxsize,
                "workers": int(self.thread is not None and self.thread.is_alive())}


worker = BoundedWorker()


def deterministic_ai(evaluation, uncovered_zones):
    findings = zone_deviations.detect_zone_deviations(
        evaluation.all_detections,
        has_active_stage=bool(evaluation.stage_evaluations),
        uncovered_zones=uncovered_zones,
    )
    enabled = observation_ai.ai_enrichment_enabled()
    return {"enabled": enabled, "status": "pending" if enabled else "disabled",
            "reason": "Анализ ИИ ожидает обработки" if enabled else "Языковая модель отключена или не настроена",
            "vision": None, "conclusion": None, "stage_mismatch": None,
            "zone_deviations": [zone_deviations.to_dict(item) for item in findings]}


def _store(observation_id, payload, *, vision=False, expected_run_id=None):
    """Only observation-local fields: delayed jobs must never reconcile alert lifecycle."""
    from django.db import close_old_connections
    from core.models import Observation
    close_old_connections()
    try:
        fields = {"ai_analysis": payload}
        data = payload.get("vision") or {}
        if vision and data.get("available"):
            fields.update(vision_stage_key=data.get("stage_key", ""),
                          vision_stage_label=data.get("stage_label", ""),
                          readiness_percent=data.get("readiness_percent"))
        rows = Observation.objects.filter(pk=observation_id)
        if expected_run_id is not None:
            rows = rows.filter(ai_analysis__execution_trace__run_id=expected_run_id)
        return rows.update(**fields) == 1
    finally:
        close_old_connections()


def enqueue(*, observation_id, site_id, image_path, image_sha256, zone_name,
            evaluation, schedule, uncovered_zones, critical_stage_ids=None, initial=None):
    payload = dict(initial or deterministic_ai(evaluation, uncovered_zones))
    if payload["status"] == "pending":
        payload["queued_at"] = datetime.now(UTC).isoformat()
        payload["expires_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    try:
        if not _store(observation_id, payload):
            return {**payload, "status": "failed", "reason": "Наблюдение не сохранено"}
        if not payload["enabled"]:
            return payload
        # These are pure matching dataclasses, never ORM instances or request objects.
        snapshot = deepcopy((evaluation, schedule))

        def run():
            from django.db import close_old_connections
            from core.models import Observation
            close_old_connections()
            try:
                row = Observation.objects.select_related("zone__site").filter(
                    pk=observation_id, zone__site_id=site_id).first()
                if row is None:
                    return
                # Reload scoped identity, while preserving the original schedule/evaluation snapshot.
                result = observation_ai.enrich_observation(
                    image_path=Path(row.image_path), image_sha256=row.image_sha256,
                    zone_name=row.zone.external_id, evaluation=snapshot[0], schedule=snapshot[1],
                    uncovered_zones=uncovered_zones, critical_stage_ids=critical_stage_ids)
                healthy = bool((result.get("vision") or {}).get("available") and
                               (result.get("conclusion") or {}).get("available"))
                result = {**result, "status": "complete" if healthy else "failed",
                          "zone_deviations": payload["zone_deviations"],
                          **({"execution_trace": payload["execution_trace"]} if "execution_trace" in payload else {}),
                          "finished_at": datetime.now(UTC).isoformat()}
                _store(observation_id, result, vision=True, expected_run_id=(payload.get("execution_trace") or {}).get("run_id"))
            except Exception:
                logger.exception("AI enrichment failed for observation %s", observation_id)
                _store(observation_id, {**payload, "status": "failed", "reason": "Сервис ИИ недоступен"},
                       expected_run_id=(payload.get("execution_trace") or {}).get("run_id"))
            finally:
                close_old_connections()

        if not worker.submit(run):
            payload = {**payload, "status": "failed", "reason": "Очередь ИИ заполнена; основной анализ сохранён"}
            _store(observation_id, payload)
        return payload
    except Exception:
        logger.exception("Could not queue observation AI")
        return {**payload, "status": "failed", "reason": "Фоновый анализ ИИ недоступен"}


def visible_status(payload):
    """A process interrupted while queued must not appear pending forever."""
    if payload.get("status") == "pending" and payload.get("expires_at"):
        try:
            if datetime.fromisoformat(payload["expires_at"]) < datetime.now(UTC):
                return {**payload, "status": "failed", "reason": "Фоновый анализ прерван или время ожидания истекло"}
        except (ValueError, TypeError):
            return {**payload, "status": "failed", "reason": "Некорректное время ожидания анализа"}
    return payload
