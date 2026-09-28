"""Заполняет БД демонстрационными данными из data/config/*.

Источник — те же файлы, что использовались до перехода на Postgres:
vocabulary.yaml, equipment_rules.yaml, demo_schedule.json,
demo_site.geojson, weather_rules.yaml. Команда идемпотентна
(update_or_create) — повторный запуск не создаёт дублей и обновляет
изменившиеся поля. После первого запуска источником правды становится
БД — редактируйте дальше через Django admin, а не файлы.

Запуск:
  python manage.py seed_demo_data
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import yaml
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    Camera,
    ConfusablePair,
    ConstructionSite,
    KnownLimitation,
    Stage,
    StageRequiredItem,
    StageRule,
    UserProfile,
    VocabularyClass,
    WeatherRule,
    Zone,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "data" / "config"


class Command(BaseCommand):
    help = "Заполнить БД демонстрационными данными из data/config/*"
    def add_arguments(self, parser):
        parser.add_argument(
            "--users-only",
            action="store_true",
            help="Инициализировать аккаунты, не изменяя рабочие справочники и график",
        )

    def handle(self, *args, **options):
        if options.get("users_only"):
            self._seed_user_profiles()
            return
        vocabulary_by_key = self._seed_vocabulary()
        zones_by_external_id = self._seed_site_and_zones()
        self._seed_cameras(zones_by_external_id)
        stages_by_external_id = self._seed_schedule(zones_by_external_id)
        self._seed_equipment_rules(stages_by_external_id, vocabulary_by_key)
        self._seed_weather_rules(stages_by_external_id)
        self._seed_user_profiles()
        self.stdout.write(self.style.SUCCESS("Сид данных завершён."))

    def _seed_vocabulary(self) -> dict[str, VocabularyClass]:
        data = yaml.safe_load((CONFIG_DIR / "vocabulary.yaml").read_text(encoding="utf-8"))
        by_key: dict[str, VocabularyClass] = {}
        for group, in_taxonomy in (("classes", True), ("distractors", False)):
            for entry in data.get(group) or []:
                obj, _ = VocabularyClass.objects.update_or_create(
                    key=entry["key"],
                    defaults={
                        "label_ru": entry["label_ru"],
                        "prompts": entry["prompts"],
                        "in_taxonomy": in_taxonomy,
                    },
                )
                by_key[obj.key] = obj
        self.stdout.write(f"Словарь классов: {len(by_key)}")
        return by_key

    def _seed_site_and_zones(self) -> dict[str, Zone]:
        geojson = json.loads((CONFIG_DIR / "demo_site.geojson").read_text(encoding="utf-8"))
        site_feature = next(
            f for f in geojson["features"] if f["properties"]["kind"] == "site_boundary"
        )
        site, _ = ConstructionSite.objects.update_or_create(
            name=site_feature["properties"]["name"],
            defaults={
                "note": geojson.get("properties", {}).get("note", ""),
                "is_demo": bool(geojson.get("properties", {}).get("is_demo", True)),
                "boundary_geojson": site_feature["geometry"],
            },
        )

        zones_by_external_id: dict[str, Zone] = {}
        for feature in geojson["features"]:
            if feature["properties"]["kind"] != "zone":
                continue
            props = feature["properties"]
            zone, _ = Zone.objects.update_or_create(
                external_id=props["id"],
                defaults={
                    "site": site,
                    "name": props["name"],
                    "description": props.get("description", ""),
                    "geometry_geojson": feature["geometry"],
                },
            )
            zones_by_external_id[zone.external_id] = zone
        self.stdout.write(f"Площадка «{site.name}», зон: {len(zones_by_external_id)}")
        return zones_by_external_id

    def _seed_cameras(self, zones_by_external_id: dict[str, Zone]) -> None:
        """По одной демо-камере на зону, координаты — центроид полигона зоны.

        Честно только такое число камер, сколько зон в демо-площадке — без
        выдумывания несуществующего масштаба.
        """
        count = 0
        for index, (external_id, zone) in enumerate(sorted(zones_by_external_id.items()), start=1):
            ring = zone.geometry_geojson["coordinates"][0]
            lons = [pt[0] for pt in ring]
            lats = [pt[1] for pt in ring]
            Camera.objects.update_or_create(
                external_id=f"cam-{index:02d}",
                defaults={
                    "zone": zone,
                    "name": f"Камера {index:02d} — {zone.name}",
                    "latitude": sum(lats) / len(lats),
                    "longitude": sum(lons) / len(lons),
                    "is_demo": True,
                    "note": "Координаты — центроид зоны, а не реальное расположение камеры.",
                },
            )
            count += 1
        self.stdout.write(f"Камер: {count}")

    def _seed_schedule(self, zones_by_external_id: dict[str, Zone]) -> dict[str, Stage]:
        data = json.loads((CONFIG_DIR / "demo_schedule.json").read_text(encoding="utf-8"))
        is_demo = bool(data.get("is_demo", True))
        stages_by_external_id: dict[str, Stage] = {}
        for entry in data["stages"]:
            zone = zones_by_external_id[entry["zone_id"]]
            stage, _ = Stage.objects.update_or_create(
                external_id=entry["stage_id"],
                defaults={
                    "zone": zone,
                    "work_code": entry.get("work_code") or entry.get("parent_work_code", ""),
                    "work_name": entry["work_name"],
                    "start_date": date.fromisoformat(entry["start_date"]),
                    "end_date": date.fromisoformat(entry["end_date"]),
                    "technology_assumption": entry.get("technology_assumption", ""),
                    "is_demo": is_demo,
                },
            )
            stages_by_external_id[stage.external_id] = stage

        # Вторым проходом: иерархия и связи. Раньше нельзя — работа может
        # ссылаться на родителя или предшественника, описанного ниже по файлу.
        links = 0
        for entry in data["stages"]:
            stage = stages_by_external_id[entry["stage_id"]]
            parent_id = entry.get("parent_stage_id")
            parent = stages_by_external_id.get(parent_id) if parent_id else None
            if stage.parent_id != (parent.pk if parent else None):
                stage.parent = parent
                stage.save(update_fields=["parent"])
            predecessors = [
                stages_by_external_id[pid]
                for pid in entry.get("predecessor_ids") or []
                if pid in stages_by_external_id
            ]
            stage.predecessors.set(predecessors)
            links += len(predecessors)

        self.stdout.write(
            f"Этапов графика: {len(stages_by_external_id)}, связей предшествования: {links}"
        )
        return stages_by_external_id

    def _seed_equipment_rules(
        self,
        stages_by_external_id: dict[str, Stage],
        vocabulary_by_key: dict[str, VocabularyClass],
    ) -> None:
        data = yaml.safe_load((CONFIG_DIR / "equipment_rules.yaml").read_text(encoding="utf-8"))

        for stage_id, entry in (data.get("stage_rules") or {}).items():
            stage = stages_by_external_id.get(stage_id)
            if stage is None:
                continue
            rule, _ = StageRule.objects.update_or_create(
                stage=stage,
                defaults={"alternatives_note": (entry.get("alternatives_note") or "").strip()},
            )
            raw_required = entry.get("required") or {}
            # `required` в YAML может быть словарём ключ -> количество (текущий
            # формат) или списком ключей без количества (старый формат, min_quantity=1).
            required_quantities = (
                raw_required if isinstance(raw_required, dict) else dict.fromkeys(raw_required, 1)
            )
            rule.required_items.exclude(vocabulary_class__key__in=required_quantities).delete()
            for key, min_quantity in required_quantities.items():
                StageRequiredItem.objects.update_or_create(
                    stage_rule=rule,
                    vocabulary_class=vocabulary_by_key[key],
                    defaults={"min_quantity": int(min_quantity)},
                )
            rule.allowed.set(vocabulary_by_key[k] for k in entry.get("allowed") or [])

        for pair in data.get("confusable_class_pairs") or []:
            key_a, key_b = sorted(pair)  # стабильный порядок для unique_together
            ConfusablePair.objects.update_or_create(
                class_a=vocabulary_by_key[key_a],
                class_b=vocabulary_by_key[key_b],
            )

        for entry in data.get("known_limitations") or []:
            KnownLimitation.objects.update_or_create(
                vocabulary_class=vocabulary_by_key[entry["class_key"]],
                issue=entry["issue"],
                defaults={"description": (entry.get("description") or "").strip()},
            )

        self.stdout.write(
            f"Правила техники: {StageRule.objects.count()}, "
            f"путаемых пар: {ConfusablePair.objects.count()}, "
            f"известных ограничений: {KnownLimitation.objects.count()}"
        )

    def _seed_weather_rules(self, stages_by_external_id: dict[str, Stage]) -> None:
        data = yaml.safe_load((CONFIG_DIR / "weather_rules.yaml").read_text(encoding="utf-8"))
        count = 0
        for entry in data.get("rules") or []:
            stage = stages_by_external_id.get(entry["stage_id"])
            if stage is None:
                continue
            WeatherRule.objects.update_or_create(
                stage=stage,
                factor=entry["factor"],
                defaults={
                    "comparison": entry["comparison"],
                    "threshold": float(entry["threshold"]),
                    "units": entry.get("units", ""),
                    "message": (entry.get("message") or "").strip(),
                },
            )
            count += 1
        self.stdout.write(f"Погодных правил: {count}")

    @transaction.atomic
    def _seed_user_profiles(self) -> None:
        """Создаёт недостающие аккаунты, не сбрасывая существующие доступы.

        Пароли берутся только из окружения при создании. Без явно заданного
        пароля новый participant имеет unusable password и войти не может.
        Повторный запуск не меняет пароли, роли и должности существующих профилей.
        """
        admin_username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        if admin_username and not User.objects.filter(username=admin_username).exists():
            password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
            if not password:
                raise CommandError("Для создания администратора задайте DJANGO_SUPERUSER_PASSWORD")
            candidate = User(username=admin_username)
            validate_password(password, user=candidate)
            User.objects.create_superuser(
                username=admin_username,
                email=os.environ.get("DJANGO_SUPERUSER_EMAIL", ""),
                password=password,
            )
        for user in User.objects.filter(is_superuser=True):
            UserProfile.objects.get_or_create(
                user=user,
                defaults={"role": UserProfile.Role.ADMIN, "position": "Руководитель проекта"},
            )

        demo_participant, created = User.objects.get_or_create(
            username="participant",
            defaults={"first_name": "Инженер", "last_name": "Участковый"},
        )
        if created:
            password = os.environ.get("SK_PARTICIPANT_PASSWORD")
            if password:
                validate_password(password, user=demo_participant)
                demo_participant.set_password(password)
            else:
                demo_participant.set_unusable_password()
            demo_participant.is_staff = False
            demo_participant.save()
        UserProfile.objects.get_or_create(
            user=demo_participant,
            defaults={"role": UserProfile.Role.PARTICIPANT, "position": "Инженер ПТО"},
        )
        self.stdout.write("Профили пользователей проверены. Существующие пароли не изменены.")
