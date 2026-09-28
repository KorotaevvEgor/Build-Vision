"""Обучение классификатора-корректора поверх CLIP-эмбеддингов коррекций инженера.

См. план, модуль «AI Learning»: вместо дообучения всего YOLO-World — лёгкий
классификатор (логистическая регрессия из scikit-learn, секунды на CPU) поверх
CLIP-эмбеддингов обрезков, которые инженер подтвердил/исправил через «Что
это?» в интерфейсе (core.models.Correction).

Честная валидация: в датасете проекта нет отдельного размеченного held-out
набора — data/config/splits.json делит только файлы на dev/val/holdout, без
разметки классов. Единственный реально размеченный человеком материал — сами
коррекции, поэтому оценка строится train/test-разбиением внутри них. При
нехватке данных (см. MIN_TOTAL_FOR_VALIDATION/MIN_SAMPLES_PER_CLASS_FOR_TEST)
валидация честно помечается недоступной, а не заменяется выдуманным числом.

Запускается в фоне через backend/app/learning.trigger_training() (subprocess,
без Celery/Redis — оправдано объёмом задачи), либо вручную:
  python scripts/train_correction_classifier.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import clip_embeddings, config, django_bridge

MIN_SAMPLES_PER_CLASS_FOR_TEST = 2
MIN_TOTAL_FOR_VALIDATION = 6
NOT_EQUIPMENT_LABEL = config.CORRECTION_NOT_EQUIPMENT_LABEL


def _label_for(correction) -> str:
    return correction.corrected_class.key if correction.corrected_class_id else NOT_EQUIPMENT_LABEL


def _resolve_crop_path(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else REPO_ROOT / raw_path


def main() -> None:
    if not django_bridge.ensure_django_ready():
        raise SystemExit("БД недоступна — обучение классификатора-корректора невозможно без Postgres")

    from core.models import Correction, ModelVersion

    # Legacy-only: коррекции других проектов не примешиваются к обучающей выборке
    # (см. план, граница AI Learning) — орфанные коррекции (observation=NULL) тоже исключены.
    corrections = list(
        Correction.objects.select_related("corrected_class").filter(
            observation__isnull=False, observation__zone__site__is_legacy=True
        )
    )
    if not corrections:
        raise SystemExit("Нет ни одной коррекции legacy-проекта — обучать не на чём")

    print(f"Найдено коррекций: {len(corrections)}")

    embeddings: list[list[float]] = []
    labels: list[str] = []
    for correction in corrections:
        crop_path = _resolve_crop_path(correction.crop_image_path)
        if not crop_path.is_file():
            print(f"[WARN] пропущена коррекция id={correction.id}: файл не найден {crop_path}")
            continue
        embeddings.append(clip_embeddings.embed_image(crop_path))
        labels.append(_label_for(correction))

    if not embeddings:
        raise SystemExit("Ни для одной коррекции не удалось прочитать файл обрезка")

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support
    from sklearn.model_selection import train_test_split

    x_all = np.array(embeddings)
    y_all = np.array(labels)
    class_counts = Counter(labels)

    can_validate = (
        len(embeddings) >= MIN_TOTAL_FOR_VALIDATION
        and len(class_counts) >= 2
        and all(count >= MIN_SAMPLES_PER_CLASS_FOR_TEST for count in class_counts.values())
    )

    metrics: dict = {"available": False}
    classifier = None

    if can_validate:
        x_train, x_test, y_train, y_test = train_test_split(
            x_all, y_all, test_size=0.25, random_state=42, stratify=y_all
        )
        eval_clf = LogisticRegression(max_iter=1000)
        eval_clf.fit(x_train, y_train)
        y_pred = eval_clf.predict(x_test)
        accuracy = accuracy_score(y_test, y_pred)
        labels_sorted = sorted(class_counts)
        precision, recall, _f1, support = precision_recall_fscore_support(
            y_test, y_pred, labels=labels_sorted, zero_division=0
        )
        metrics = {
            "available": True,
            "train_count": len(x_train),
            "test_count": len(x_test),
            "accuracy": round(float(accuracy), 4),
            "per_class": [
                {
                    "class_key": label,
                    "precision": round(float(p), 4),
                    "recall": round(float(r), 4),
                    "support": int(s),
                }
                for label, p, r, s in zip(labels_sorted, precision, recall, support, strict=True)
            ],
            "note": (
                "Метрики измерены на отложенной части накопленных коррекций (train/test-"
                "разбиение) — отдельного размеченного held-out датасета в проекте нет."
            ),
        }
        classifier = LogisticRegression(max_iter=1000)
        classifier.fit(x_all, y_all)
    else:
        metrics["reason"] = (
            f"Недостаточно данных для честной валидации: нужно минимум {MIN_TOTAL_FOR_VALIDATION} "
            f"коррекций и минимум {MIN_SAMPLES_PER_CLASS_FOR_TEST} на класс как минимум для 2 "
            f"классов (сейчас коррекций: {len(embeddings)}, классов: {len(class_counts)})."
        )
        print(f"[WARN] {metrics['reason']}")
        if len(class_counts) >= 2:
            classifier = LogisticRegression(max_iter=1000)
            classifier.fit(x_all, y_all)
        else:
            print("[WARN] Меньше двух классов среди коррекций — классификатор не обучен, только метрики честно помечены недоступными.")

    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    version_label = f"v{ModelVersion.objects.count() + 1}"
    artifact_path_str = ""

    if classifier is not None:
        import joblib

        artifact_path = config.MODELS_DIR / f"correction_classifier_{version_label}.joblib"
        joblib.dump({"model": classifier, "classes": sorted(class_counts)}, artifact_path)
        artifact_path_str = str(artifact_path)

    previous_production = ModelVersion.objects.filter(status=ModelVersion.Status.PRODUCTION).first()

    version = ModelVersion.objects.create(
        version_label=version_label,
        status=ModelVersion.Status.CANDIDATE,
        artifact_path=artifact_path_str,
        trained_at=datetime.now(UTC),
        training_sample_count=len(embeddings),
        metrics_json=metrics,
        based_on=previous_production,
    )
    print(
        f"[OK] Создан кандидат {version.version_label} (id={version.id}), "
        f"метрики: {json.dumps(metrics, ensure_ascii=False)}"
    )


if __name__ == "__main__":
    main()
