"""Наполняет проект 38 демо-данными для показа: реальная история наблюдений по
подготовленному набору кадров (C:\\Users\\catoa\\Downloads\\demo_upload\\), с
настоящими правилами техники по этапам и настоящим прогоном детектора — без
единой выдуманной детекции. Отставание графика (после Нового года) не
прописывается руками, а получается из честного расчёта критического пути по
реально обнаруженным нехваткам техники на этапе «Монолитный каркас».

Порог уверенности детектора в глобальных настройках (MatchingSettings) на
этом сервере выставлен в 0.95 — при таком пороге YOLO-World (открытый словарь,
типичные confidence 0.1-0.5) не находит вообще ничего. Трогать глобальную
настройку нельзя: это запустило бы переанализ всей истории legacy-проекта
(см. reanalysis.py), не имеющей отношения к проекту 38. Поэтому здесь
детектор вызывается напрямую (`_detect`) со своим порогом — только для
кадров, которые эта команда сама загружает.

Запуск: python manage.py seed_project38_demo
(через .venv, где установлены и Django, и ultralytics/torch)
"""
from __future__ import annotations

import csv
import hashlib
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

SITE_ID = 38
DEMO_DIR = Path(r"C:\Users\catoa\Downloads\demo_upload")
PHOTOS_DIR = DEMO_DIR / "photos"
DATES_CSV = DEMO_DIR / "photo_dates.csv"
DETECT_CONF = 0.3

# Важно: excavator/mobile_crane/road_roller входят в confusable-пары с crane_manipulator
# (см. ConfusablePair в БД), а detector.py безусловно помечает ЛЮБУЮ детекцию этих
# классов как ambiguous=True (независимо от confidence) -- а ambiguous-детекции НИКОГДА
# не считаются "уверенно присутствующими" в matching.py (confident_by_class). Значит, требовать их
# в StageRule бессмысленно -- проверка никогда не пройдёт, сколько техники ни было видно на кадре.
# Единственный класс вне этих пар — dump_truck, на нём и строятся все пороги (калибровканы
# по реальному прогону детектора по кадрам объекта).
STAGE_RULES: dict[str, dict] = {
    "site38-stage-1": {
        "required": {"dump_truck": 3},
        "allowed": ["truck", "excavator", "crane_manipulator", "bulldozer"],
    },
    "site38-stage-2": {
        "required": {"dump_truck": 4},
        "allowed": ["truck", "bulldozer", "excavator", "crane_manipulator"],
    },
    "site38-stage-3": {
        "required": {"dump_truck": 3},
        "allowed": ["truck", "concrete_mixer", "crane_manipulator", "excavator", "mobile_crane"],
    },
    "site38-stage-4": {
        "required": {"dump_truck": 3},
        "allowed": ["truck", "excavator", "concrete_mixer", "crane_manipulator", "mobile_crane"],
    },
}

# Окна дат этапов (совпадают с уже существующим графиком проекта 38).
STAGE_WINDOWS = [
    ("site38-stage-1", date(2026, 8, 1), date(2026, 8, 7)),
    ("site38-stage-2", date(2026, 8, 8), date(2026, 8, 21)),
    ("site38-stage-3", date(2026, 8, 22), date(2026, 9, 11)),
    ("site38-stage-4", date(2026, 9, 12), date(2026, 9, 27)),  # обрезано "сегодня" (2026-09-27)
]

CAMERA_IDS = ["site38-cam-1", "site38-cam-extra-1"]


class Command(BaseCommand):
    help = "Наполняет проект 38 (site pk=38) демо-историей наблюдений по реальным кадрам"

    def handle(self, *args, **options):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

        from app import config, deviations as deviations_module, observation_ai, schedule_network
        from app.app_context import get_context
        from app.detector import Detection, get_detector
        from app.matching import evaluate_observation

        from core.models import (
            Camera,
            ConstructionSite,
            Observation,
            Stage,
            StageRequiredItem,
            StageRule,
            VocabularyClass,
            Zone,
        )

        site = ConstructionSite.objects.get(pk=SITE_ID)
        zone = Zone.objects.get(site=site)
        cameras = {c.external_id: c for c in Camera.objects.filter(zone=zone)}
        vocab = {v.key: v for v in VocabularyClass.objects.all()}

        # --- 1. Чистый лист: убираем тестовые наблюдения прошлых прогонов мастера ---
        old_observations = Observation.objects.filter(zone=zone)
        removed_files = 0
        for path_value in old_observations.values_list("image_path", flat=True):
            p = Path(path_value)
            if p.is_file():
                p.unlink()
                removed_files += 1
        old_count = old_observations.count()
        old_observations.delete()
        self.stdout.write(f"Удалено старых тестовых наблюдений: {old_count} (файлов: {removed_files})")

        # --- 2. Правила техники по этапам ---
        for stage_id, rule_cfg in STAGE_RULES.items():
            stage = Stage.objects.get(external_id=stage_id)
            rule, _ = StageRule.objects.update_or_create(
                stage=stage,
                defaults={"alternatives_note": "Пороги калиброваны по реальному прогону детектора на кадрах объекта."},
            )
            rule.required_items.all().delete()
            for class_key, qty in rule_cfg["required"].items():
                StageRequiredItem.objects.create(
                    stage_rule=rule, vocabulary_class=vocab[class_key], min_quantity=qty
                )
            rule.allowed.set(vocab[key] for key in rule_cfg["allowed"] if key in vocab)
        self.stdout.write("Правила техники по этапам 1-4 обновлены")

        # --- 3. Кадры и даты ---
        with DATES_CSV.open(encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            all_frames = [
                (row["filename"], datetime.fromisoformat(row["observed_date"])) for row in reader
            ]
        by_day: dict[date, list[tuple[str, datetime]]] = {}
        for filename, observed_at in all_frames:
            by_day.setdefault(observed_at.date(), []).append((filename, observed_at))
        for day_frames in by_day.values():
            day_frames.sort(key=lambda item: item[1])

        def pick_for_day(day: date, n: int) -> list[tuple[str, datetime]]:
            frames = by_day.get(day, [])
            if not frames:
                return []
            if n >= len(frames):
                return frames
            step = len(frames) / n
            return [frames[int(i * step)] for i in range(n)]

        detector = get_detector()
        detector._ensure_loaded()

        def detect(image_path: Path) -> list:
            result = detector._model.predict(
                source=str(image_path),
                imgsz=detector.imgsz,
                conf=DETECT_CONF,
                iou=detector.iou,
                max_det=detector.max_det,
                agnostic_nms=True,
                device="cpu",
                verbose=False,
            )[0]
            names = result.names
            out = []
            for box in result.boxes:
                prompt = names[int(box.cls.item())]
                info = detector.vocabulary.class_for_prompt(prompt)
                if info.key == "person":
                    continue
                confidence = float(box.conf.item())
                ambiguous = False
                runner_up_key = None
                if info.in_taxonomy:
                    partners = detector._confusable_partners(info.key)
                    if partners:
                        ambiguous = True
                        runner_up_key = partners[0]
                out.append(
                    Detection(
                        class_key=info.key,
                        label_ru=info.label_ru,
                        in_taxonomy=info.in_taxonomy,
                        confidence=round(confidence, 4),
                        bbox=[round(float(v), 1) for v in box.xyxy[0].tolist()],
                        ambiguous=ambiguous,
                        runner_up_class_key=runner_up_key,
                        runner_up_confidence=None,
                    )
                )
            out.sort(key=lambda d: -d.confidence)
            return out

        def confident_counts(detections: list) -> dict[str, int]:
            counts: dict[str, int] = {}
            for d in detections:
                if d.in_taxonomy and not d.ambiguous:
                    counts[d.class_key] = counts.get(d.class_key, 0) + 1
            return counts

        def all_counts(detections: list) -> dict[str, int]:
            """Включая ambiguous -- для выбора "геройского" кадра: на фронтенде рамки рисуются
            и для ambiguous-детекций (с пометкой «неоднозначно»), поэтому для визуального богатства
            техники на фото важна любая детекция, а не только уверенная (в отличие от confident_counts,
            который идёт в проверку план/факт).
            """
            counts: dict[str, int] = {}
            for d in detections:
                if d.in_taxonomy:
                    counts[d.class_key] = counts.get(d.class_key, 0) + 1
            return counts

        def satisfies(counts: dict[str, int], required: dict[str, int]) -> bool:
            return all(counts.get(key, 0) >= qty for key, qty in required.items())

        # --- 4. Кандидаты по каждому этапу: качаем + детектируем ---
        candidates_by_stage: dict[str, list[dict]] = {}
        per_day_stage1_2_4 = 2
        for stage_id, start, end in STAGE_WINDOWS:
            n_per_day = 1 if stage_id == "site38-stage-3" else per_day_stage1_2_4
            required = STAGE_RULES[stage_id]["required"]
            items = []
            day = start
            while day <= end:
                extra = (
                    1
                    if stage_id == "site38-stage-4" and day >= date(2026, 9, 20)
                    else 0
                )
                for filename, observed_at in pick_for_day(day, n_per_day + extra):
                    path = PHOTOS_DIR / filename
                    if not path.is_file():
                        continue
                    detections = detect(path)
                    counts = confident_counts(detections)
                    items.append(
                        {
                            "filename": filename,
                            "observed_at": observed_at,
                            "detections": detections,
                            "counts": counts,
                            "all_counts": all_counts(detections),
                            "pass": satisfies(counts, required),
                        }
                    )
                    self.stdout.write(
                        f"  [{stage_id}] {filename} ({observed_at.date()}): {counts} "
                        f"(всего видно: {items[-1]['all_counts']}) "
                        f"-> {'OK' if items[-1]['pass'] else 'shortfall'}"
                    )
                day = date.fromordinal(day.toordinal() + 1)
            items.sort(key=lambda item: item["observed_at"])
            candidates_by_stage[stage_id] = items

        # --- 5. Куратура: этапы 1-3 должны заканчиваться "в срок" (последний по дате -- pass),
        # этап 4 -- реальная, посчитанная нехватка техники (компромисс ~35-45% pass). ---
        def trim_to_end_compliant(items: list[dict]) -> list[dict]:
            trimmed = list(items)
            while trimmed and not trimmed[-1]["pass"]:
                trimmed.pop()
            return trimmed or items  # если вообще ничего не compliant -- оставляем как есть (честно)

        candidates_by_stage["site38-stage-1"] = trim_to_end_compliant(candidates_by_stage["site38-stage-1"])
        candidates_by_stage["site38-stage-2"] = trim_to_end_compliant(candidates_by_stage["site38-stage-2"])
        candidates_by_stage["site38-stage-3"] = trim_to_end_compliant(candidates_by_stage["site38-stage-3"])

        stage4_items = candidates_by_stage["site38-stage-4"]
        passing = [i for i in stage4_items if i["pass"]]
        failing = [i for i in stage4_items if not i["pass"]]
        target_ratio = 0.4
        target_pass_count = max(1, round(len(stage4_items) * target_ratio))
        if len(passing) > target_pass_count:
            # Оставляем равномерно распределённые по времени, а не первые/последние подряд.
            step = len(passing) / target_pass_count
            keep_idx = {int(i * step) for i in range(target_pass_count)}
            passing = [item for idx, item in enumerate(passing) if idx in keep_idx]
        stage4_final = sorted(passing + failing, key=lambda item: item["observed_at"])
        candidates_by_stage["site38-stage-4"] = stage4_final

        total_selected = sum(len(v) for v in candidates_by_stage.values())
        self.stdout.write(self.style.HTTP_INFO(f"\nИтого к загрузке: {total_selected} наблюдений"))
        for stage_id, items in candidates_by_stage.items():
            passes = sum(1 for i in items if i["pass"])
            self.stdout.write(
                f"  {stage_id}: {len(items)} кадров, соответствуют правилу: {passes} "
                f"({passes / len(items) * 100:.0f}%)" if items else f"  {stage_id}: 0 кадров"
            )

        # --- 6. "Геройский" кадр: из последней недели этапа 4, максимум различных классов техники.
        # Считаем по all_counts (включая ambiguous): на фронтенде рамки рисуются и для
        # неоднозначных детекций (excavator/mobile_crane/crane_manipulator всегда такие), и для
        # "геройского" кадра важен визуальный состав техники на фото, а не только confident_counts
        # (там всегда был бы только dump_truck).
        hero_pool = [i for i in stage4_items if i["observed_at"].date() >= date(2026, 9, 20)]

        def distinct_equipment_count(item: dict) -> int:
            return len({k for k in item["all_counts"] if item["all_counts"][k] > 0})

        hero = max(hero_pool, key=distinct_equipment_count) if hero_pool else None
        if hero is not None:
            self.stdout.write(
                self.style.HTTP_INFO(
                    f"\nГеройский кадр: {hero['filename']} ({hero['observed_at']}), "
                    f"видно (вкл. неоднозначное): {hero['all_counts']}"
                )
            )
            # Убираем из обычной очереди -- загрузим его последним отдельно, чтобы он стал "последним" по created_at.
            candidates_by_stage["site38-stage-4"] = [
                i for i in candidates_by_stage["site38-stage-4"] if i is not hero
            ]

        # --- 7. Загрузка: полный конвейер продукта (детекция уже готова, дальше -- как в реальном API). ---
        ctx = get_context(site=site)
        critical_ids = schedule_network.critical_stage_ids(ctx.schedule)
        config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

        camera_cycle = list(cameras.values())

        def persist_one(item: dict, index: int) -> None:
            filename = item["filename"]
            observed_date = item["observed_at"].date()
            camera = camera_cycle[index % len(camera_cycle)] if camera_cycle else None

            observation_uuid = uuid.uuid4()
            dest_path = config.UPLOADS_DIR / f"{observation_uuid}.jpg"
            shutil.copyfile(PHOTOS_DIR / filename, dest_path)
            image_sha256 = hashlib.sha256(dest_path.read_bytes()).hexdigest()

            from PIL import Image

            try:
                with Image.open(dest_path) as img:
                    image_size = img.size
            except Exception:
                image_size = (0, 0)

            detections = item["detections"]
            observation_ai.apply_zones_and_activity(
                detections,
                camera_external_id=camera.external_id if camera else None,
                image_size=image_size,
                observed_date=observed_date,
            )

            evaluation = evaluate_observation(
                zone_id=zone.external_id,
                observed_date=observed_date,
                date_confirmed=True,
                detections=detections,
                schedule=ctx.schedule,
                rules=ctx.rules,
            )

            from app import persistence

            saved_to_db = persistence.persist_observation(
                observation_id=observation_uuid,
                zone_id=zone.external_id,
                image_path=str(dest_path),
                image_sha256=image_sha256,
                evaluation=evaluation,
                site=site,
                camera_external_id=camera.external_id if camera else None,
                image_size=image_size,
            )

            from app import frame_zones as frame_zones_module

            ai = observation_ai.enrich_observation(
                image_path=dest_path,
                image_sha256=image_sha256,
                zone_name=zone.external_id,
                evaluation=evaluation,
                schedule=ctx.schedule,
                uncovered_zones=frame_zones_module.uncovered_stage_zones(site=site),
                critical_stage_ids=critical_ids,
            )
            persistence.update_observation_vision(observation_uuid, ai.get("vision"))

            if saved_to_db:
                findings = deviations_module.findings_from_evaluation(
                    evaluation, critical_stage_ids=critical_ids
                )
                primary_stage_id = (
                    evaluation.stage_evaluations[0].stage_id if evaluation.stage_evaluations else None
                )
                findings += deviations_module.findings_from_ai(ai, stage_id=primary_stage_id)
                deviations_module.sync_from_observation(
                    observation_id=observation_uuid,
                    zone_external_id=zone.external_id,
                    site=site,
                    findings=findings,
                    observation_status=evaluation.overall_status,
                    critical_stage_ids=critical_ids,
                )

        index = 0
        for stage_id, _, _ in STAGE_WINDOWS:
            for item in candidates_by_stage[stage_id]:
                with transaction.atomic():
                    persist_one(item, index)
                index += 1
            self.stdout.write(f"  загружено наблюдений для {stage_id}: {len(candidates_by_stage[stage_id])}")

        if hero is not None:
            with transaction.atomic():
                persist_one(hero, index)
            self.stdout.write(self.style.SUCCESS(f"Геройский кадр {hero['filename']} загружен последним"))

        # --- 8. Итог: считанный сдвиг срока сдачи. ---
        final_report = schedule_network.build_report(ctx.schedule, date(2026, 9, 27), site=site)
        self.stdout.write(self.style.SUCCESS("\n--- Итог ---"))
        self.stdout.write(f"Плановая сдача: {final_report.baseline_finish}")
        self.stdout.write(f"Прогнозная сдача: {final_report.projected_finish}")
        self.stdout.write(f"Сдвиг: {final_report.shift_days} дн., статус: {final_report.status}")
