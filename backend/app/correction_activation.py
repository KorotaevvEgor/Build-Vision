"""Publication gate for explicitly selected project correction candidates."""
import math
from pathlib import Path
from . import config

MIN_VALIDATION_ACCURACY = 0.8


def activation_problem(version, *, completed):
    if version.status != "candidate" or not completed or not version.trained_at:
        return "Публиковать можно только кандидата из завершённого обучения проекта"
    artifact = Path(version.artifact_path).resolve()
    if not artifact.is_relative_to(config.MODELS_DIR.resolve()) or not artifact.is_file() or artifact.stat().st_size == 0:
        return "Артефакт обученной модели недоступен"
    metrics = version.metrics_json or {}
    accuracy = metrics.get("accuracy")
    if (metrics.get("available") is not True or metrics.get("split_unit") != "observation"
            or not isinstance(metrics.get("test_count"), int) or metrics["test_count"] < 1
            or isinstance(accuracy, bool) or not isinstance(accuracy, (int, float))
            or not math.isfinite(accuracy) or not MIN_VALIDATION_ACCURACY <= accuracy <= 1):
        return "Нужна проверка на отложенных наблюдениях с точностью не ниже 80%; добавьте независимые размеченные снимки"
    return None
