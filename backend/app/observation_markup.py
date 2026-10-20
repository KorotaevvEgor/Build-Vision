"""Stored visual annotations. These never replace detector evidence or plan/fact checks."""

from __future__ import annotations

import json
import math
import os
import uuid
from collections import defaultdict
from dataclasses import asdict

from . import config
from .llm.equipment import EquipmentLocation


def _path(observation_id):
    return config.UPLOADS_DIR / "ai_markup" / f"{uuid.UUID(str(observation_id))}.json"


def save_markup(observation_id, image_sha256: str, location: EquipmentLocation) -> dict:
    if not location.available:
        raise ValueError("Cannot store an unavailable analysis")
    counts = defaultdict(lambda: {"count": 0, "max_confidence": 0.0})
    items = []
    for box in location.items:
        x1, y1, x2, y2 = box.box
        if not (
            all(math.isfinite(v) for v in box.box)
            and 0 <= x1 < x2 <= 1
            and 0 <= y1 < y2 <= 1
        ):
            raise ValueError("Invalid normalized box")
        items.append(asdict(box))
        entry = counts[box.class_key]
        entry.update(class_key=box.class_key, label_ru=box.label_ru)
        entry["count"] += 1
        entry["max_confidence"] = max(entry["max_confidence"], box.confidence)
    payload = {
        "version": 1,
        "image_sha256": image_sha256,
        "source": "aitunnel",
        "available": True,
        "items": items,
        "counts": sorted(counts.values(), key=lambda c: (-c["count"], c["class_key"])),
        "model": location.model,
        "cached": location.cached,
        "error": None,
    }
    path = _path(observation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        pending.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)
    return payload


def read_markup(observation_id, image_sha256: str) -> dict | None:
    try:
        payload = json.loads(_path(observation_id).read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or payload.get("image_sha256") != image_sha256
            or payload.get("available") is not True
            or not isinstance(payload.get("items"), list)
            or not isinstance(payload.get("counts"), list)
        ):
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None
