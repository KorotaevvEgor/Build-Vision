"""Stable model/threshold provenance, computed without exposing environment secrets."""
from . import config, runtime_settings

def detector_context(detector, execution_trace=None):
    weights_name = getattr(detector, "weights", config.DEFAULT_MODEL_WEIGHTS)
    weights = config.MODELS_DIR/weights_name
    stat = weights.stat() if weights.exists() else None
    trace = execution_trace or {}
    correction = trace.get('correction', {})
    return {'weights':weights_name,'weights_size':stat.st_size if stat else None,
            'weights_mtime_ns':stat.st_mtime_ns if stat else None,
            'confidence':trace.get('detector', {}).get('confidence', runtime_settings.load().detector_confidence),
            'class_thresholds':getattr(detector,'class_thresholds',{}) if isinstance(getattr(detector,'class_thresholds',{}),dict) else {},
            'correction_version':correction.get('version_id'),
            'execution':trace}
