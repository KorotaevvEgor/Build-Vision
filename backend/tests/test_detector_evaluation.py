"""Metric regressions: duplicates and unknown counts must not inflate quality."""
import pytest
from pathlib import Path

from scripts.evaluate_detector import calibrate_counts, score_image


def test_class_threshold_gate_is_opt_in_and_never_lowers_global_threshold(monkeypatch):
    from types import SimpleNamespace

    from backend.app import detector as module
    monkeypatch.setattr(module.django_bridge, "ensure_django_ready", lambda: False)
    monkeypatch.setattr(module.runtime_settings, "load", lambda: SimpleNamespace(detector_confidence=.25))
    scalar = lambda value: SimpleNamespace(item=lambda: value)
    boxes = [SimpleNamespace(cls=scalar(0), conf=scalar(.6),
                             xyxy=[SimpleNamespace(tolist=lambda: [0, 0, 10, 10])])]
    fake = SimpleNamespace(predict=lambda **kwargs: [SimpleNamespace(names={0: "dump truck"}, boxes=boxes)])
    monkeypatch.delenv("SK_DETECTOR_CLASS_THRESHOLDS_JSON", raising=False)
    normal = module.Detector()
    normal._model = fake
    assert len(normal.detect(None, apply_correction_classifier=False)) == 1
    calibrated = module.Detector(class_thresholds={"dump_truck": .8})
    calibrated._model = fake
    assert calibrated.detect(None, apply_correction_classifier=False) == []
    monkeypatch.setattr(module.runtime_settings, "load", lambda: SimpleNamespace(detector_confidence=.7))
    lower = module.Detector(class_thresholds={"dump_truck": .1})
    lower._model = fake
    assert lower.detect(None, apply_correction_classifier=False) == []
    monkeypatch.setenv("SK_DETECTOR_CLASS_THRESHOLDS_JSON", '{"dump_truck": 0.8}')
    assert module.Detector().class_thresholds == {"dump_truck": .8}


@pytest.mark.parametrize("thresholds", [{"dump_truck": float("nan")}, {"dump_truck": 1.2}, {"typo": .5}])
def test_invalid_class_thresholds_fail_clearly(monkeypatch, thresholds):
    from backend.app import detector as module
    monkeypatch.setattr(module.django_bridge, "ensure_django_ready", lambda: False)
    with pytest.raises(ValueError):
        module.Detector(class_thresholds=thresholds)


def test_duplicate_box_is_false_positive():
    box = {"class_key": "excavator", "bbox": [0, 0, 10, 10], "confidence": .9}
    result = score_image({"objects": [box], "counts": {"excavator": [1, 1]}}, [box, box])
    assert result["bbox"]["excavator"] == {"tp": 1, "fp": 1, "fn": 0}
    assert result["counts"]["excavator"]["absolute_error_lower_bound"] == 1


def test_class_mismatch_is_miss_and_false_positive():
    truth = {"class_key": "excavator", "bbox": [0, 0, 10, 10]}
    wrong = {**truth, "class_key": "truck", "confidence": .9}
    result = score_image({"objects": [truth], "bbox_classes": ["excavator", "truck"]}, [wrong])
    assert result["bbox"]["excavator"]["fn"] == 1
    assert result["bbox"]["truck"]["fp"] == 1


def test_count_interval_and_unannotated_class():
    predictions = [{"class_key": "excavator"}] * 3 + [{"class_key": "truck"}]
    result = score_image({"counts": {"excavator": [2, 3]}}, predictions)
    assert result["counts"]["excavator"]["absolute_error_lower_bound"] == 0
    assert "truck" not in result["counts"]
    assert result["bbox"] == {}


def test_negative_only_calibration_never_publishes_threshold():
    payload = {"detector": {"confidence": .25}, "images": [
        {"file_name": str(i), "detections": [{"class_key": "dump_truck", "confidence": .5}]}
        for i in range(6)], "annotations": {"images": [
        {"file_name": str(i), "counts": {"dump_truck": [0, 0]}} for i in range(6)]}}
    result = calibrate_counts(payload)
    assert result["activation_recommended"] is False
    assert result["class_thresholds"] == {}
    assert result["classes"]["dump_truck"]["candidate_threshold"] > .5

def test_inference_admission_is_bounded_and_recovers():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.detector import Detector,DetectorBusyError
    detector=object.__new__(Detector)
    detector._request_slots=threading.BoundedSemaphore(2)
    ready=threading.Barrier(3);release=threading.Event()
    def slow(*args,**kwargs):
        ready.wait(timeout=3);release.wait(timeout=3);return []
    detector._detect=slow
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs=[executor.submit(detector.detect,Path('unused')) for _ in range(2)]
        ready.wait(timeout=3)
        with pytest.raises(DetectorBusyError):detector.detect(Path('unused'))
        release.set()
        assert all(job.result(timeout=3)==[] for job in jobs)
    detector._detect=lambda *args,**kwargs:[]
    assert detector.detect(Path('unused'))==[]
