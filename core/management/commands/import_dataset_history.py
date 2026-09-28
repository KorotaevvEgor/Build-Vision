"""Импорт хроники объектов из выданного набора снимков.

Зачем. Без истории система нечитаема: надзорный орган работает не с одним
кадром, а с объектом за месяцы. Выданные 100 снимков это позволяют — в них
впечатаны даты, а сами кадры складываются в обходы нескольких площадок.

Что делает команда:

1. читает разбиение по объектам (data/config/dataset_objects.json) и результат
   разбора снимков моделью (data/config/dataset_scan.json);
2. создаёт объекты, участки и точки съёмки. Точка съёмки внутри обхода — это
   и есть камера: у кадров одного обхода разные ракурсы одной площадки;
3. прогоняет детектор по каждому кадру и сохраняет наблюдения с датой из
   штампа;
4. строит календарный график под фактическую хронологию: стадии берутся из
   того, что модель увидела на снимках, плановые даты сдвигаются так, чтобы
   часть объектов отставала, а часть шла с опережением;
5. прогоняет жизненный цикл отклонений по хронологии, чтобы лента событий
   заполнилась настоящей историей: что открылось, что повторилось, что
   закрылось следующим обходом.

Честные оговорки, которые команда переносит в данные:

* даты наблюдений сдвинуты вперёд относительно штампа, чтобы объекты были
  живыми на дату показа. Исходный штамп сохраняется в объяснении наблюдения;
* плановые даты графика придуманы: календарного плана заказчика нет;
* кадры без штампа даты импортируются с `date_confirmed=False` и не участвуют
  ни в хронологии, ни в расчёте сроков;
* координаты объектов условные, адресов в материалах нет.

Запуск:
  python manage.py import_dataset_history
  python manage.py import_dataset_history --reset
  python manage.py import_dataset_history --only obj-brick-yard
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

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

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "data" / "config"
IMAGES_DIR = REPO_ROOT / "data" / "raw" / "images"
UPLOADS_DIR = REPO_ROOT / "data" / "uploads"

if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))


def _square_polygon(latitude: float, longitude: float, half_side_deg: float = 0.0016) -> dict:
    """Условная квадратная граница участка вокруг точки.

    Настоящих границ в материалах нет. Квадрат честнее произвольного
    многоугольника: его никто не примет за обведённый по кадастру контур.
    """
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [longitude - half_side_deg, latitude - half_side_deg],
                [longitude + half_side_deg, latitude - half_side_deg],
                [longitude + half_side_deg, latitude + half_side_deg],
                [longitude - half_side_deg, latitude + half_side_deg],
                [longitude - half_side_deg, latitude - half_side_deg],
            ]
        ],
    }


class Command(BaseCommand):
    help = "Импортировать хронику объектов из выданного набора снимков"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Удалить ранее импортированные объекты перед загрузкой",
        )
        parser.add_argument(
            "--only",
            default="",
            help="Импортировать только один объект по его идентификатору",
        )
        parser.add_argument(
            "--skip-detector",
            action="store_true",
            help="Не прогонять детектор (быстрая проверка структуры без детекций)",
        )

    def handle(self, *args, **options):
        objects_config = self._read_json(CONFIG_DIR / "dataset_objects.json")
        scan = {
            item["file"]: item
            for item in self._read_json(CONFIG_DIR / "dataset_scan.json")["images"]
        }

        wanted = options["only"].strip()
        objects = [
            entry
            for entry in objects_config["objects"]
            if not wanted or entry["id"] == wanted
        ]
        if not objects:
            raise CommandError(f"Объект не найден в конфигурации: {wanted}")

        if options["reset"]:
            self._reset([entry["id"] for entry in objects])

        detector = None
        if not options["skip_detector"]:
            from app.detector import get_detector

            detector = get_detector()
            self.stdout.write("Детектор загружен, прогон займёт несколько минут")

        vocabulary = {item.key: item for item in VocabularyClass.objects.all()}
        if not vocabulary:
            raise CommandError("Словарь классов пуст — сначала выполните seed_demo_data")

        today = datetime.now(UTC).date()
        for entry in objects:
            self._import_object(
                entry=entry,
                scan=scan,
                stage_rules=objects_config["stage_rules"],
                vocabulary=vocabulary,
                detector=detector,
                today=today,
                notes=objects_config,
            )

        self.stdout.write(self.style.SUCCESS("Импорт хроники завершён."))

    # ------------------------------------------------------------------
    # Чтение и очистка
    # ------------------------------------------------------------------

    def _read_json(self, path: Path) -> dict:
        if not path.is_file():
            raise CommandError(f"Нет файла: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _reset(self, object_ids: list[str]) -> None:
        """Удаляет ранее импортированные объекты вместе со всей их историей.

        Наблюдения удаляются явно: ссылка на зону защищена от каскада, и это
        правильно — историю анализа нельзя снести случайным удалением проекта в
        админке. Здесь удаление осознанное, поэтому сносим и скопированные файлы снимков,
        иначе каталог загрузок растёт при каждом повторном импорте.
        """
        sites = list(ConstructionSite.objects.filter(external_key__in=object_ids))
        if not sites:
            self.stdout.write("Ранее импортированных объектов не найдено")
            return

        observations = Observation.objects.filter(zone__site__in=sites)
        removed_files = 0
        for path_value in observations.values_list("image_path", flat=True):
            path = Path(path_value)
            if path.is_file() and path.parent.resolve() == UPLOADS_DIR.resolve():
                path.unlink()
                removed_files += 1
        observation_count = observations.count()
        observations.delete()

        for site in sites:
            site.delete()

        self.stdout.write(
            f"Удалено объектов: {len(sites)}, наблюдений: {observation_count}, "
            f"файлов снимков: {removed_files}"
        )

    # ------------------------------------------------------------------
    # Импорт одного объекта
    # ------------------------------------------------------------------

    def _import_object(self, *, entry, scan, stage_rules, vocabulary, detector, today, notes) -> None:
        self.stdout.write(self.style.HTTP_INFO(f"\n{entry['name']}"))

        frames = self._prepare_frames(entry, scan, today)
        if not frames:
            self.stdout.write("  нет пригодных кадров, пропущено")
            return

        site, zone = self._create_site(entry, notes)
        cameras = self._create_cameras(entry, zone, frames)
        self._create_schedule(entry, zone, frames, stage_rules, vocabulary)
        self._create_observations(
            site=site,
            zone=zone,
            cameras=cameras,
            frames=frames,
            detector=detector,
        )

    def _prepare_frames(self, entry, scan, today) -> list[dict]:
        """Готовит кадры объекта: сдвигает даты, раскладывает по обходам.

        Кадр со сдвинутой датой в будущем отбрасывается: наблюдение, которого
        ещё не было, сломало бы и график, и расчёт сроков.
        """
        shift = timedelta(days=int(entry.get("date_shift_days", 0)))
        frames: list[dict] = []
        for file_name in entry["files"]:
            item = scan.get(file_name)
            if item is None or not item.get("available"):
                self.stdout.write(f"  {file_name}: нет разбора, пропущен")
                continue
            image_path = IMAGES_DIR / file_name
            if not image_path.is_file():
                self.stdout.write(f"  {file_name}: файла нет на диске, пропущен")
                continue

            original = item.get("observed_date")
            shifted = None
            if original:
                shifted = date.fromisoformat(original) + shift
                if shifted > today:
                    self.stdout.write(f"  {file_name}: сдвинутая дата в будущем, пропущен")
                    continue

            frames.append(
                {
                    "file": file_name,
                    "path": image_path,
                    "original_date": original,
                    "observed_date": shifted,
                    "stage_key": item["stage_key"],
                    "stage_label": item["stage_label"],
                    "readiness": item.get("readiness_percent"),
                }
            )

        # Датированные кадры идут по хронологии, недатированные — в конец:
        # они не участвуют в сроках, но остаются в истории объекта.
        frames.sort(key=lambda f: (f["observed_date"] is None, f["observed_date"] or date.min))
        return frames

    def _create_site(self, entry, notes) -> tuple[ConstructionSite, Zone]:
        site, _ = ConstructionSite.objects.update_or_create(
            external_key=entry["id"],
            defaults={
                "name": entry["name"],
                "address": entry["address"],
                "status": ConstructionSite.Status.CONSTRUCTION,
                "latitude": entry["latitude"],
                "longitude": entry["longitude"],
                "is_demo": True,
                "boundary_geojson": _square_polygon(entry["latitude"], entry["longitude"]),
                "note": " ".join(
                    [
                        entry["comment"],
                        notes["coordinates_note"],
                        notes["date_shift_note"] if entry.get("date_shift_days") else "",
                    ]
                ).strip(),
            },
        )
        zone, _ = Zone.objects.update_or_create(
            external_id=f"{entry['id']}-zone",
            defaults={
                "site": site,
                "name": f"{entry['name']}: основной участок",
                "description": "Участок совпадает с площадкой: деления на участки в материалах нет.",
                "geometry_geojson": _square_polygon(entry["latitude"], entry["longitude"], 0.0012),
            },
        )
        return site, zone

    #: Больше четырёх точек съёмки на площадку заводить бессмысленно: камеры ставят
    #: по периметру, и четырёх ракурсов хватает, чтобы покрыть обычную площадку.
    #: Без ограничения объект без дат получил бы по камере на каждый снимок.
    MAX_CAMERAS_PER_SITE = 4

    def _create_cameras(self, entry, zone, frames) -> dict[int, Camera]:
        """Точки съёмки по числу кадров в самом крупном обходе.

        Допущение, которое надо назвать вслух: считаем, что в каждом обходе
        снимают одни и те же точки в одном порядке. Проверить это по кадрам
        нельзя, но без такого соответствия история камеры не собирается вообще.
        """
        by_date: dict[date | None, int] = {}
        for frame in frames:
            by_date[frame["observed_date"]] = by_date.get(frame["observed_date"], 0) + 1
        slots = min(max(by_date.values()) if by_date else 1, self.MAX_CAMERAS_PER_SITE)

        cameras: dict[int, Camera] = {}
        for index in range(slots):
            camera, _ = Camera.objects.update_or_create(
                external_id=f"{entry['id']}-cam-{index + 1:02d}",
                defaults={
                    "zone": zone,
                    "name": f"Точка съёмки {index + 1}",
                    "latitude": entry["latitude"],
                    "longitude": entry["longitude"],
                    "is_demo": True,
                    "note": (
                        "Точка съёмки восстановлена по порядку кадров в обходе: "
                        "считается, что в каждом обходе снимают одни и те же ракурсы "
                        "в одном порядке. Координаты условные."
                    ),
                },
            )
            cameras[index] = camera
        self.stdout.write(f"  точек съёмки: {len(cameras)}")
        return cameras

    def _session_stages(self, dated: list[dict]) -> list[tuple[date, str]]:
        """Один обход — одна стадия, определённая большинством ракурсов.

        Без этого график рассыпается: на одной площадке в один день один ракурс
        показывает свайное поле, другой — угол котлована, и покадровое чтение даёт
        метание между стадиями в пределах одного дня. Площадка в конкретный день
        находится в одной стадии, и голосование ракурсов — честный способ её выбрать.
        """
        by_session: dict[date, list[str]] = {}
        for frame in dated:
            if frame["stage_key"] == "undetermined":
                continue
            by_session.setdefault(frame["observed_date"], []).append(frame["stage_key"])

        sessions: list[tuple[date, str]] = []
        for session_date in sorted(by_session):
            keys = by_session[session_date]
            # При равном числе голосов берём ту, что встретилась первой в обходе:
            # произвольный, но устойчивый выбор лучше случайного.
            winner = max(dict.fromkeys(keys), key=lambda key: (keys.count(key), -keys.index(key)))
            sessions.append((session_date, winner))
        return sessions

    def _create_schedule(self, entry, zone, frames, stage_rules, vocabulary) -> dict[str, Stage]:
        """Строит график по фактической хронологии стадий на снимках."""
        dated = [f for f in frames if f["observed_date"]]
        if not dated:
            self.stdout.write("  дат на кадрах нет — график не строится")
            return {}

        sessions = self._session_stages(dated)
        # Соседние обходы с одной стадией — это одна работа графика, а не несколько.
        periods: list[dict] = []
        for session_date, stage_key in sessions:
            if periods and periods[-1]["stage_key"] == stage_key:
                periods[-1]["end"] = session_date
                continue
            periods.append({"stage_key": stage_key, "start": session_date, "end": session_date})

        if not periods:
            self.stdout.write("  стадии по кадрам не определены — график не строится")
            return {}

        # Работа длится до начала следующей: без этого работа, заснятая один раз,
        # выглядела бы однодневной, а в графике зияли бы дыры между этапами.
        for index, period in enumerate(periods):
            if index + 1 < len(periods):
                period["end"] = periods[index + 1]["start"] - timedelta(days=1)
            else:
                period["end"] = max(period["end"], period["start"] + timedelta(days=13))

        plan_shift = timedelta(days=int(entry.get("plan_shift_days", 0)))
        stages: dict[str, Stage] = {}
        previous: Stage | None = None

        for index, period in enumerate(periods, start=1):
            rule_config = stage_rules.get(period["stage_key"])
            if rule_config is None:
                continue
            stage, _ = Stage.objects.update_or_create(
                external_id=f"{entry['id']}-stage-{index:02d}",
                defaults={
                    "zone": zone,
                    "work_code": rule_config["work_code"],
                    "work_name": rule_config["work_name"],
                    "start_date": period["start"] + plan_shift,
                    "end_date": period["end"] + plan_shift,
                    "technology_assumption": rule_config["alternatives_note"],
                    "is_demo": True,
                },
            )
            if previous is not None:
                stage.predecessors.set([previous])
            previous = stage
            stages[period["stage_key"]] = stage

            rule, _ = StageRule.objects.update_or_create(
                stage=stage, defaults={"alternatives_note": rule_config["alternatives_note"]}
            )
            required = rule_config.get("required") or {}
            rule.required_items.exclude(vocabulary_class__key__in=required).delete()
            for class_key, quantity in required.items():
                if class_key in vocabulary:
                    StageRequiredItem.objects.update_or_create(
                        stage_rule=rule,
                        vocabulary_class=vocabulary[class_key],
                        defaults={"min_quantity": int(quantity)},
                    )
            rule.allowed.set(
                vocabulary[key] for key in rule_config.get("allowed", []) if key in vocabulary
            )

        self.stdout.write(
            f"  работ графика: {len(stages)}, плановый сдвиг {entry.get('plan_shift_days', 0)} дн."
        )
        return stages

    def _create_observations(self, *, site, zone, cameras, frames, detector) -> None:
        from app import deviations as deviations_module
        from app import frame_zones as frame_zones_module
        from app import observation_ai, schedule_network, zone_deviations
        from app.app_context import get_context
        from app.matching import evaluate_observation

        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        context = get_context(site=site)
        critical_ids = schedule_network.critical_stage_ids(context.schedule)

        slot_by_date: dict[date | None, int] = {}
        created = 0
        deviations_opened = 0
        deviations_closed = 0

        for frame in frames:
            position = slot_by_date.get(frame["observed_date"], 0)
            slot_by_date[frame["observed_date"]] = position + 1
            # Если в обходе кадров больше, чем точек съёмки, остаток распределяется
            # по кругу: лучше два кадра одной камеры за день, чем десяток камер-призраков.
            camera = cameras[position % len(cameras)]

            observation_uuid = uuid.uuid4()
            stored_path = UPLOADS_DIR / f"{observation_uuid}.png"
            shutil.copyfile(frame["path"], stored_path)
            image_sha256 = hashlib.sha256(stored_path.read_bytes()).hexdigest()

            detections = detector.detect(stored_path, apply_correction_classifier=False) if detector else []
            image_size = self._image_size(stored_path)
            observation_ai.apply_zones_and_activity(
                detections,
                camera_external_id=camera.external_id,
                image_size=image_size,
                observed_date=frame["observed_date"],
            )

            evaluation = evaluate_observation(
                zone_id=zone.external_id,
                observed_date=frame["observed_date"],
                date_confirmed=frame["observed_date"] is not None,
                detections=detections,
                schedule=context.schedule,
                rules=context.rules,
            )

            with transaction.atomic():
                observation = self._save_observation(
                    observation_uuid=observation_uuid,
                    zone=zone,
                    camera=camera,
                    stored_path=stored_path,
                    image_sha256=image_sha256,
                    image_size=image_size,
                    frame=frame,
                    evaluation=evaluation,
                )
                self._save_detections(observation, detections)
                self._save_stage_evaluations(observation, evaluation)

            findings = deviations_module.findings_from_evaluation(
                evaluation, critical_stage_ids=critical_ids
            )
            # Отклонения по зонам считаются и здесь: у импортированных объектов зоны кадра
            # ещё не размечены, и система обязана сказать об этом прямо, а не молчать:
            # без разметки работа и простой не определяются вообще.
            zone_findings = zone_deviations.detect_zone_deviations(
                evaluation.all_detections,
                has_active_stage=bool(evaluation.stage_evaluations),
                uncovered_zones=frame_zones_module.uncovered_stage_zones(site=site),
            )
            primary_stage_id = (
                evaluation.stage_evaluations[0].stage_id if evaluation.stage_evaluations else None
            )
            findings += deviations_module.findings_from_ai(
                {"zone_deviations": [zone_deviations.to_dict(item) for item in zone_findings]},
                stage_id=primary_stage_id,
            )
            lifecycle = deviations_module.sync_from_observation(
                observation_id=observation.pk,
                zone_external_id=zone.external_id,
                site=site,
                findings=findings,
                observation_status=evaluation.overall_status,
                critical_stage_ids=critical_ids,
            )
            deviations_opened += len(lifecycle.get("opened", []))
            deviations_closed += len(lifecycle.get("auto_resolved", []))
            created += 1

        self.stdout.write(
            f"  наблюдений: {created}, отклонений открыто: {deviations_opened}, "
            f"закрыто следующим обходом: {deviations_closed}"
        )

    def _save_observation(
        self, *, observation_uuid, zone, camera, stored_path, image_sha256, image_size, frame, evaluation
    ) -> Observation:
        stamp_note = (
            f"Штамп даты на кадре: {frame['original_date']}. "
            "Дата наблюдения сдвинута вперёд для демонстрации на живых сроках."
            if frame["original_date"]
            else "Штамп даты на кадре отсутствует — дата наблюдения не подтверждена."
        )
        return Observation.objects.create(
            id=observation_uuid,
            zone=zone,
            camera=camera,
            image_width=image_size[0] or None,
            image_height=image_size[1] or None,
            image_path=str(stored_path),
            image_sha256=image_sha256,
            observed_date=frame["observed_date"],
            date_confirmed=frame["observed_date"] is not None,
            overall_status=evaluation.overall_status,
            overall_explanation=f"{evaluation.overall_explanation_ru} {stamp_note}",
            # Оценка по фото уже посчитана при разборе датасета — переспрашивать модель
            # ради того же ответа на сотне кадров незачем.
            vision_stage_key=frame["stage_key"],
            vision_stage_label=frame["stage_label"],
            readiness_percent=frame["readiness"],
        )

    def _save_detections(self, observation, detections) -> None:
        from core.models import Detection as DetectionRow

        DetectionRow.objects.bulk_create(
            DetectionRow(
                observation=observation,
                class_key=d.class_key,
                label_ru=d.label_ru,
                in_taxonomy=d.in_taxonomy,
                confidence=d.confidence,
                bbox=d.bbox,
                ambiguous=d.ambiguous,
                runner_up_class_key=d.runner_up_class_key or "",
                frame_zone_id=getattr(d, "frame_zone_id", None),
                activity=getattr(d, "activity", "unknown"),
                activity_reason=getattr(d, "activity_reason", "")[:300],
            )
            for d in detections
        )

    def _save_stage_evaluations(self, observation, evaluation) -> None:
        from core.models import StageEvaluationRecord

        for item in evaluation.stage_evaluations:
            StageEvaluationRecord.objects.create(
                observation=observation,
                stage=Stage.objects.filter(external_id=item.stage_id).first(),
                work_name_snapshot=item.work_name,
                status=item.status,
                explanation=item.explanation_ru,
                required_snapshot=item.required,
                allowed_snapshot=item.allowed,
                quantity_checks_snapshot=[
                    {
                        "class_key": c.class_key,
                        "label_ru": c.label_ru,
                        "required_qty": c.required_qty,
                        "actual_qty": c.actual_qty,
                        "satisfied": c.satisfied,
                    }
                    for c in item.quantity_checks
                ],
                missing_required=item.missing_required,
                unexpected_detections=[
                    {"class_key": d.class_key, "label_ru": d.label_ru, "confidence": d.confidence}
                    for d in item.unexpected_detections
                ],
                ambiguous_detections=[
                    {"class_key": d.class_key, "label_ru": d.label_ru, "confidence": d.confidence}
                    for d in item.ambiguous_detections
                ],
            )

    def _image_size(self, path: Path) -> tuple[int, int]:
        try:
            from PIL import Image

            with Image.open(path) as image:
                return image.size
        except Exception:
            return (0, 0)
