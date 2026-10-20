from pathlib import Path
from types import SimpleNamespace

from app import detector as module
from app.analysis_context import detector_context
from app.correction_activation import activation_problem


def test_scoped_correction_lookup_never_falls_back(monkeypatch):
    import sys
    filters = []
    class Query:
        def filter(self, **kw): filters.append(kw); return self
        def exclude(self, **kw): return self
        def order_by(self, *args): return self
        def first(self): return None
    fake = SimpleNamespace(objects=Query(), Status=SimpleNamespace(PRODUCTION="production"))
    monkeypatch.setitem(sys.modules, "core.models", SimpleNamespace(ModelVersion=fake))
    monkeypatch.setattr(module.django_bridge, "ensure_django_ready", lambda: True)
    detector = module.Detector()
    trace = {}
    assert detector._load_correction_classifier(site_id=42, execution_trace=trace) is None
    assert filters == [{"status": "production", "site_id": 42}]
    assert trace == {"status": "unused", "reason": "no_production_version"}


def test_no_ambiguous_boxes_never_load_optional_classifier(monkeypatch):
    detector = module.Detector()
    monkeypatch.setattr(detector, "_load_correction_classifier", lambda **kw: (_ for _ in ()).throw(AssertionError()))
    trace = {}
    detector._apply_correction_classifier(Path("unused"), [], site_id=42, execution_trace=trace)
    assert trace["status"] == "unused"
    assert trace["reason"] == "no_ambiguous_detections"


def test_context_never_uses_shared_classifier_cache():
    detector = SimpleNamespace(_correction_classifier_cache=(99, {}))
    assert detector_context(detector)["correction_version"] is None
    trace = {"correction": {"version_id": 7, "status": "participated"}}
    assert detector_context(detector, trace)["correction_version"] == 7


def test_activation_requires_real_artifact_and_independent_validation(tmp_path, monkeypatch):
    from app import correction_activation as activation
    monkeypatch.setattr(activation.config, "MODELS_DIR", tmp_path)
    artifact = tmp_path / "candidate.joblib"
    artifact.write_bytes(b"real artifact")
    version = SimpleNamespace(status="candidate", trained_at=True, artifact_path=str(artifact),
        metrics_json={"available": True, "split_unit": "observation", "test_count": 4, "accuracy": .9})
    assert activation_problem(version, completed=True) is None
    assert activation_problem(version, completed=False)
    version.metrics_json["accuracy"] = .79
    assert activation_problem(version, completed=True)
    version.metrics_json["accuracy"] = float("nan")
    assert activation_problem(version, completed=True)
    version.metrics_json["accuracy"] = .9
    artifact.unlink()
    assert activation_problem(version, completed=True)


def test_classifier_records_actual_predictions_and_keeps_ambiguity(tmp_path, monkeypatch):
    from PIL import Image
    from app import clip_embeddings
    image = tmp_path / "scene.png"
    Image.new("RGB", (20, 20)).save(image)
    detector = module.Detector()
    seen = []
    def load(**kwargs):
        seen.append(kwargs["site_id"])
        kwargs["execution_trace"]["version_id"] = 8
        return {"model": SimpleNamespace(predict=lambda values: ["dump_truck"])}
    monkeypatch.setattr(detector, "_load_correction_classifier", load)
    monkeypatch.setattr(clip_embeddings, "embed_image_from_pil", lambda crop: [1, 2])
    detection = module.Detection("excavator", "Экскаватор", True, .8, [0, 0, 10, 10], True, None, None)
    trace = {}
    detector._apply_correction_classifier(image, [detection], site_id=42, execution_trace=trace)
    assert seen == [42]
    assert trace == {"candidate_count": 1, "classified_count": 1, "changed_count": 1,
                     "version_id": 8, "status": "participated", "reason": "classified"}
    assert detection.class_key == "dump_truck"
    assert detection.ambiguous is True


def test_context_reports_threshold_used_and_custom_weights(monkeypatch):
    from app import analysis_context
    monkeypatch.setattr(analysis_context.runtime_settings, "load", lambda: SimpleNamespace(detector_confidence=.9))
    result = detector_context(SimpleNamespace(weights="custom.pt"), {"detector": {"confidence": .3}})
    assert result["confidence"] == .3
    assert result["weights"] == "custom.pt"


def test_reanalysis_uses_project_scope_and_passes_same_trace(tmp_path, monkeypatch):
    import sys
    from app import reanalysis, persistence
    image = tmp_path / "source.png"
    image.write_bytes(b"source")
    sites = [SimpleNamespace(pk=1, is_legacy=True), SimpleNamespace(pk=9, is_legacy=False)]
    observation = SimpleNamespace(image_path=str(image), camera_id=None, image_width=10,
        image_height=10, observed_date=None, date_confirmed=False, captured_at=None,
        image_sha256="source-hash", zone=SimpleNamespace(external_id="zone"))
    rows = SimpleNamespace(select_related=lambda *args: rows, order_by=lambda *args: [observation])
    monkeypatch.setitem(sys.modules, "core.models", SimpleNamespace(
        ConstructionSite=SimpleNamespace(objects=SimpleNamespace(all=lambda: sites)),
        Observation=SimpleNamespace(objects=SimpleNamespace(filter=lambda **kwargs: rows))))
    monkeypatch.setattr(reanalysis.django_bridge, "ensure_django_ready", lambda: True)
    monkeypatch.setattr(reanalysis, "get_context", lambda **kw: SimpleNamespace(schedule=None, rules=None))
    scopes, contexts, saved = [], [], []
    def detect(path, **kwargs):
        scopes.append(kwargs["site_id"])
        kwargs["execution_trace"].update(run_id=str(kwargs["site_id"]), detector={"confidence": .4})
        return []
    monkeypatch.setattr(reanalysis, "get_detector", lambda: SimpleNamespace(detect=detect))
    monkeypatch.setattr(reanalysis.observation_ai, "apply_zones_and_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(reanalysis, "evaluate_observation", lambda **kwargs: contexts.append(kwargs["analysis_context"]) or "evaluation")
    monkeypatch.setattr(persistence, "replace_observation_results", lambda *args, **kwargs: saved.append(kwargs["execution_trace"]))
    assert reanalysis.reanalyze_all_observations() == {"total": 2, "updated": 2, "errors": 0}
    assert scopes == [1, 9]
    assert [context["execution"] for context in contexts] == saved
    assert saved[0] is not saved[1]


def test_replacement_archives_source_ai_and_clears_stale_results(monkeypatch):
    import sys
    from app import persistence
    manager = SimpleNamespace(filter=lambda **kwargs: manager, delete=lambda: None, bulk_create=lambda rows: None)
    monkeypatch.setitem(sys.modules, "core.models", SimpleNamespace(Detection=SimpleNamespace(objects=manager),
        Stage=object, StageEvaluationRecord=SimpleNamespace(objects=manager)))
    relation = SimpleNamespace(values=lambda *args: [{"source": "original"}])
    original = {"status": "complete", "execution_trace": {"run_id": "old"}}
    saved_fields = []
    observation = SimpleNamespace(analysis_history=[], overall_status="old", overall_explanation="old reason",
        ai_analysis=original, detections=relation, stage_evaluations=relation,
        vision_stage_key="old", vision_stage_label="old", readiness_percent=55,
        save=lambda **kwargs: saved_fields.extend(kwargs["update_fields"]))
    evaluation = SimpleNamespace(overall_status="new", overall_explanation_ru="new reason", all_detections=[], stage_evaluations=[])
    trace = {"run_id": "new"}
    persistence.replace_observation_results(observation, evaluation, execution_trace=trace)
    assert observation.analysis_history[0]["ai_analysis"] == original
    assert observation.analysis_history[0]["detections"] == [{"source": "original"}]
    assert observation.ai_analysis["execution_trace"] == trace
    assert observation.ai_analysis["vision"] is None
    assert observation.readiness_percent is None
    assert "ai_analysis" in saved_fields


def test_late_background_write_is_guarded_by_detector_run(monkeypatch):
    import sys
    import django.db
    from app import background_analysis
    filters = []
    manager = SimpleNamespace(filter=lambda **kwargs: filters.append(kwargs) or manager,
                              update=lambda **kwargs: 0)
    monkeypatch.setitem(sys.modules, "core.models", SimpleNamespace(Observation=SimpleNamespace(objects=manager)))
    monkeypatch.setattr(django.db, "close_old_connections", lambda: None)
    assert background_analysis._store("observation", {"status": "complete"}, expected_run_id="old") is False
    assert filters == [{"pk": "observation"}, {"ai_analysis__execution_trace__run_id": "old"}]
