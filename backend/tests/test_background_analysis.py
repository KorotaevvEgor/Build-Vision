"""Regression checks for request isolation and queue backpressure."""
import io
import threading
import time
from datetime import date
from types import SimpleNamespace

from fastapi import UploadFile

from app import background_analysis as bg
from app import projects_router as router


def test_bounded_worker_returns_without_waiting_and_rejects_full_queue():
    worker = bg.BoundedWorker(capacity=1)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def slow():
        started.set()
        release.wait(3)
    try:
        start = time.monotonic()
        assert worker.submit(slow)
        assert time.monotonic() - start < 0.5
        assert started.wait(1)
        assert worker.submit(finished.set)
        assert not worker.submit(lambda: None)
        assert worker.health() == {"queued": 1, "capacity": 1, "workers": 1}
    finally:
        release.set()
    assert finished.wait(2)


def test_worker_survives_service_exception():
    worker = bg.BoundedWorker(capacity=2)
    finished = threading.Event()
    def failure():
        raise RuntimeError("LLM offline")
    assert worker.submit(failure)
    assert worker.submit(finished.set)
    assert finished.wait(2)


def test_pipeline_persists_and_syncs_geometry_without_calling_llm(tmp_path, monkeypatch):
    evaluation = SimpleNamespace(
        zone_id="zone", observed_date=date(2026, 10, 16), date_confirmed=True,
        overall_status="ok", overall_status_label_ru="ok", overall_explanation_ru="ok",
        all_detections=[], stage_evaluations=[])
    schedule = SimpleNamespace(stages_for_zone=lambda zone: ["stage"])
    monkeypatch.setattr(router, "get_context", lambda **kw: SimpleNamespace(schedule=schedule, rules=[]))
    monkeypatch.setattr(router.config, "UPLOADS_DIR", tmp_path)
    monkeypatch.setattr(router, "get_detector", lambda: SimpleNamespace(detect=lambda *a, **kw: []))
    monkeypatch.setattr(router.observation_ai, "apply_zones_and_activity", lambda *a, **kw: None)
    monkeypatch.setattr(router, "evaluate_observation", lambda **kw: evaluation)
    monkeypatch.setattr(router.persistence, "persist_observation", lambda **kw: True)
    monkeypatch.setattr(router.schedule_network, "critical_stage_ids", lambda schedule: set())
    monkeypatch.setattr(router.frame_zones, "uncovered_stage_zones", lambda **kw: ["uncovered"])
    monkeypatch.setattr(bg.observation_ai, "ai_enrichment_enabled", lambda: True)
    findings = [{"kind": "geometry"}]
    monkeypatch.setattr(bg.zone_deviations, "detect_zone_deviations", lambda *a, **kw: findings)
    monkeypatch.setattr(bg.zone_deviations, "to_dict", lambda item: item)
    calls = []
    monkeypatch.setattr(router.deviations_module, "findings_from_evaluation", lambda *a, **kw: [])
    monkeypatch.setattr(router.deviations_module, "findings_from_ai", lambda ai, **kw: ai["zone_deviations"])
    monkeypatch.setattr(router.deviations_module, "sync_from_observation", lambda **kw: calls.append(kw) or {})
    def llm_must_not_run(**kw):
        raise AssertionError("External LLM called in request")
    monkeypatch.setattr(router.observation_ai, "enrich_observation", llm_must_not_run)
    queued = []
    monkeypatch.setattr(bg, "enqueue", lambda **kw: queued.append(kw) or kw["initial"])
    result = router._run_observation_pipeline(
        site=SimpleNamespace(pk=4, is_legacy=False), zone_id="zone",
        observed_date=evaluation.observed_date, date_confirmed=True, camera_id=None,
        image=UploadFile(filename="image.jpg", file=io.BytesIO(b"image")))
    assert result["saved_to_db"] is True
    assert result["ai"]["status"] == "pending"
    assert result["ai"]["zone_deviations"] == findings
    assert calls[0]["findings"] == findings
    assert queued[0]["site_id"] == 4


def test_queue_saturation_is_durable_failed_enrichment(monkeypatch):
    stored = []
    monkeypatch.setattr(bg, "_store", lambda oid, payload: stored.append(payload) or True)
    monkeypatch.setattr(bg.worker, "submit", lambda job: False)
    result = bg.enqueue(
        observation_id="id", site_id=1, image_path="photo", image_sha256="hash",
        zone_name="z", evaluation=None, schedule=None, uncovered_zones=[],
        initial={"enabled": True, "status": "pending", "zone_deviations": []})
    assert result["status"] == "failed"
    assert stored[-1]["status"] == "failed"


def test_service_failure_is_saved_without_alert_lifecycle(monkeypatch):
    import sys
    import django.db
    from pathlib import Path
    monkeypatch.setattr(django.db, "close_old_connections", lambda: None)
    row = SimpleNamespace(image_path="photo", image_sha256="hash", zone=SimpleNamespace(external_id="z"))
    query = SimpleNamespace(select_related=lambda *a: query, filter=lambda **kw: query, first=lambda: row)
    monkeypatch.setitem(sys.modules, "core.models", SimpleNamespace(Observation=SimpleNamespace(objects=query)))
    stored, jobs = [], []
    monkeypatch.setattr(bg, "_store", lambda oid, payload, **kw: stored.append(payload) or True)
    monkeypatch.setattr(bg.worker, "submit", lambda job: jobs.append(job) or True)
    def fail(**kw):
        raise RuntimeError("offline")
    monkeypatch.setattr(bg.observation_ai, "enrich_observation", fail)
    result = bg.enqueue(observation_id="id", site_id=1, image_path=Path("photo"), image_sha256="hash",
                        zone_name="z", evaluation=None, schedule=None, uncovered_zones=[],
                        initial={"enabled": True, "status": "pending", "zone_deviations": []})
    assert result["status"] == "pending"
    jobs[0]()
    assert stored[-1]["status"] == "failed"


def test_interrupted_pending_job_becomes_visible_failure():
    assert bg.visible_status({"status": "pending", "expires_at": "2020-01-01T00:00:00+00:00"})["status"] == "failed"
