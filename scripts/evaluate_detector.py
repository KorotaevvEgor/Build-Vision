"""Evaluate the actual application detector; never interpret predictions as labels.

JSON annotations: {image_root, provenance, images: [{file_name, counts:
{class_key: [min,max]}, objects: [{class_key,bbox}], bbox_classes: [...]}]}.
Only explicitly annotated classes are scored. Empty objects with bbox_classes
means a verified negative; omitted objects means localization is not evaluated.
Also accepts an existing flat YOLO dataset via --yolo-dir (class 0 excavator).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1]))
    area = lambda box: max(0, box[2]-box[0]) * max(0, box[3]-box[1])
    union = area(a) + area(b) - intersection
    return intersection / union if union else 0.0


def score_image(annotation, predictions, iou_threshold=.5):
    counts = Counter(p["class_key"] for p in predictions)
    count_scores = {}
    for key, (low, high) in annotation.get("counts", {}).items():
        if not 0 <= low <= high:
            raise ValueError("Invalid count interval")
        count_scores[key] = {"expected": [low, high], "predicted": counts[key],
            "absolute_error_lower_bound": max(low-counts[key], counts[key]-high, 0)}
    scores = {}
    if "objects" in annotation:
        classes = annotation.get("bbox_classes", sorted({o["class_key"] for o in annotation["objects"]}))
        for key in classes:
            truth = [o for o in annotation["objects"] if o["class_key"] == key]
            predicted = sorted((p for p in predictions if p["class_key"] == key),
                               key=lambda p: -p["confidence"])
            matched = set()
            for prediction in predicted:
                available = [(iou(prediction["bbox"], obj["bbox"]), index)
                             for index, obj in enumerate(truth) if index not in matched]
                if available:
                    overlap, index = max(available)
                    if overlap >= iou_threshold:
                        matched.add(index)
            scores[key] = {"tp": len(matched), "fp": len(predicted)-len(matched),
                           "fn": len(truth)-len(matched)}
    return {"counts": count_scores, "bbox": scores}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def calibrate_counts(payload):
    """Exploratory alternating-scene calibration, never automatic activation.

    Precision/recall here are IMAGE PRESENCE metrics, not box precision.
    Filtering saved post-NMS predictions cannot reproduce lower-threshold NMS.
    """
    annotations = payload["annotations"]["images"]
    records = {r["file_name"]: r for r in payload["images"]}
    base = payload["detector"]["confidence"]
    thresholds = sorted({base, *(t for t in (.35, .5, .65, .8, .9, .95, .99) if t >= base)})
    groups = {"calibration": annotations[::2], "verification": annotations[1::2]}
    keys = sorted({k for a in annotations for k in a.get("counts", {})})
    classes = {}
    for key in keys:
        table = {}
        for group, images in groups.items():
            rows = []
            for threshold in thresholds:
                errors = []
                tp = fp = fn = positives = 0
                for ann in images:
                    if key not in ann.get("counts", {}):
                        continue
                    low, high = ann["counts"][key]
                    count = sum(p["class_key"] == key and p["confidence"] >= threshold
                                for p in records[ann["file_name"]]["detections"])
                    errors.append(max(low-count, count-high, 0))
                    positives += low > 0
                    tp += low > 0 and count > 0
                    fp += high == 0 and count > 0
                    fn += low > 0 and count == 0
                rows.append({"threshold": threshold, "images": len(errors), "positive_images": positives,
                    "count_mae_lower_bound": sum(errors)/len(errors) if errors else None,
                    "presence_tp": tp, "presence_fp": fp, "presence_fn": fn,
                    "presence_precision": tp/(tp+fp) if tp+fp else None,
                    "presence_recall": tp/(tp+fn) if tp+fn else None})
            table[group] = rows
        available = [r for r in table["calibration"] if r["images"]]
        candidate = min(available, key=lambda r: (r["count_mae_lower_bound"], r["threshold"])) if available else None
        classes[key] = {"candidate_threshold": candidate["threshold"] if candidate else None, "sweep": table,
                        "decision": "Exploratory only: small single-annotator sample and unverified scene independence; do not activate"}
    return {"activation_recommended": False, "class_thresholds": {}, "classes": classes,
            "partitions": {k: [a["file_name"] for a in v] for k, v in groups.items()},
            "limitations": "Alternating fixed annotation order; distinct scenes visually, no camera-group identifiers. Threshold selection uses calibration only; verification never selects thresholds. Positive examples required; presence is not bbox precision."}


def load_yolo(directory, limit):
    from PIL import Image
    paths = sorted(p for p in directory.glob("*") if p.suffix.lower() in {".jpg", ".png", ".jpeg"})
    if limit and limit < len(paths):
        paths = [paths[int(i*len(paths)/limit)] for i in range(limit)]
    records = []
    for path in paths:
        with Image.open(path) as image:
            width, height = image.size
        objects = []
        for line in path.with_suffix(".txt").read_text().splitlines():
            cls, x, y, w, h = map(float, line.split())
            if cls != 0:
                raise ValueError("This source adapter supports only documented class 0 excavator")
            objects.append({"class_key": "excavator", "bbox": [
                (x-w/2)*width, (y-h/2)*height, (x+w/2)*width, (y+h/2)*height]})
        records.append({"file_name": path.name, "objects": objects,
                        "counts": {"excavator": [len(objects), len(objects)]}})
    return {"image_root": str(directory.resolve()), "images": records,
            "provenance": "Existing external source YOLO labels; class 0 excavator only; not independent holdout"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--annotations", type=Path)
    source.add_argument("--yolo-dir", type=Path)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--predictions", type=Path, help="Replay a previous evaluation output without inference")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calibration-output", type=Path, help="Exploratory count/presence threshold sweep; no settings changes")
    args = parser.parse_args()
    annotation = (json.loads(args.annotations.read_text(encoding="utf-8")) if args.annotations
                  else load_yolo(args.yolo_dir, args.limit))
    if not annotation["images"]:
        raise ValueError("No annotated images")
    image_root = ROOT / annotation["image_root"]
    metadata = {}
    previous = None
    if args.predictions:
        previous_run = json.loads(args.predictions.read_text(encoding="utf-8"))
        previous = {r["file_name"]: r for r in previous_run["images"]}
        metadata = previous_run["detector"]
    else:
        from backend.app import config, runtime_settings
        from backend.app.detector import Detector
        detector = Detector()
        weights = config.MODELS_DIR / detector.weights
        if not weights.is_file():
            raise FileNotFoundError("Evaluation requires cached local weights")
        settings = runtime_settings.load()
        metadata = {"weights": detector.weights, "weights_sha256": sha256(weights),
                    "imgsz": detector.imgsz, "iou": detector.iou, "max_det": detector.max_det,
                    "confidence": settings.detector_confidence,
                    "runtime_settings_from_database": settings.from_database,
                    "actual_prompts": detector.vocabulary.prompts,
                    "class_thresholds": detector.class_thresholds,
                    "versions": {name: version(name) for name in ("ultralytics", "torch", "numpy")},
                    "vocabulary_sha256": sha256(config.VOCABULARY_PATH),
                    "correction_classifier": False, "device": "cpu", "agnostic_nms": True}
    records = []
    for ann in annotation["images"]:
        path = image_root / ann["file_name"]
        digest = sha256(path)
        started = time.perf_counter()
        if previous is None:
            if runtime_settings.load().detector_confidence != metadata["confidence"]:
                raise RuntimeError("Runtime threshold changed during evaluation")
            predictions = [asdict(d) for d in detector.detect(path, apply_correction_classifier=False)]
        else:
            old = previous[ann["file_name"]]
            if old["image_sha256"] != digest:
                raise ValueError("Image differs from saved predictions")
            predictions = old["detections"]
        records.append({"file_name": ann["file_name"], "image_sha256": digest,
                        "seconds": round(time.perf_counter()-started, 3), "detections": predictions,
                        "scores": score_image(ann, predictions)})
        print(f"{ann['file_name']}: {len(predictions)} boxes", flush=True)
    bbox = {}
    errors = {}
    for record in records:
        for key, value in record["scores"]["bbox"].items():
            totals = bbox.setdefault(key, Counter())
            totals.update(value)
        for key, value in record["scores"]["counts"].items():
            errors.setdefault(key, []).append(value["absolute_error_lower_bound"])
    summary = {"bbox_iou_0.5": {key: {**dict(v),
        "precision": v["tp"]/(v["tp"]+v["fp"]) if v["tp"]+v["fp"] else None,
        "recall": v["tp"]/(v["tp"]+v["fn"]) if v["tp"]+v["fn"] else None} for key, v in bbox.items()},
        "count_mae_lower_bound": {key: sum(v)/len(v) for key, v in errors.items()}}
    payload = {"provenance": annotation["provenance"], "detector": metadata,
               "annotations": annotation, "images": records, "summary": summary}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.calibration_output:
        args.calibration_output.parent.mkdir(parents=True, exist_ok=True)
        args.calibration_output.write_text(json.dumps(calibrate_counts(payload), indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
