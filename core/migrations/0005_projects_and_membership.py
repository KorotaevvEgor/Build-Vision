"""Расширяет ConstructionSite до полноценного «проекта» и добавляет членства.

Закрепляет ровно один существующий проект (самый ранний по pk — тот, что
использовался как единственная площадка до этой миграции) как legacy-проект
и сохраняет доступ всех существующих активных пользователей к нему. Это
единоразовое действие: повторные прогоны migrate не создают дублей
(get_or_create) и не восстанавливают отозванные позже членства, потому что
RunPython-функция выполняется один раз при применении миграции, а не при
каждом запуске приложения.
"""

from __future__ import annotations

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def pin_legacy_project(apps, schema_editor):
    ConstructionSite = apps.get_model("core", "ConstructionSite")
    ProjectMembership = apps.get_model("core", "ProjectMembership")
    User = apps.get_model("auth", "User")

    legacy_site = ConstructionSite.objects.order_by("pk").first()
    if legacy_site is None:
        return

    legacy_site.is_legacy = True
    legacy_site.save(update_fields=["is_legacy"])

    for user in User.objects.filter(is_active=True):
        ProjectMembership.objects.get_or_create(site=legacy_site, user=user)


def unpin_legacy_project(apps, schema_editor):
    # Осознанно no-op: откат миграции не должен молча удалять данные о
    # членстве, которые к этому моменту могли уже использоваться в проде.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_correction_modelversion"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="constructionsite",
            name="boundary_geojson",
            field=models.JSONField(
                blank=True,
                help_text='{"type": "Polygon", "coordinates": [[[lon, lat], ...]]}. Пусто — граница ещё не задана.',
                null=True,
                verbose_name="Граница площадки (GeoJSON Polygon)",
            ),
        ),
        migrations.AddField(
            model_name="constructionsite",
            name="address",
            field=models.CharField(blank=True, max_length=300, verbose_name="Адрес"),
        ),
        migrations.AddField(
            model_name="constructionsite",
            name="status",
            field=models.CharField(
                choices=[
                    ("preparation", "Подготовка"),
                    ("construction", "Строительство"),
                    ("paused", "Приостановлен"),
                    ("completed", "Завершён"),
                ],
                default="construction",
                max_length=16,
                verbose_name="Статус проекта",
            ),
        ),
        migrations.AddField(
            model_name="constructionsite",
            name="latitude",
            field=models.FloatField(blank=True, null=True, verbose_name="Широта (точка на карте)"),
        ),
        migrations.AddField(
            model_name="constructionsite",
            name="longitude",
            field=models.FloatField(blank=True, null=True, verbose_name="Долгота (точка на карте)"),
        ),
        migrations.AddField(
            model_name="constructionsite",
            name="is_legacy",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Ровно один проект может быть закреплён как legacy — к нему обращаются старые "
                    "/api/... маршруты для совместимости с уже установленным APK. Устанавливается один раз "
                    "миграцией, вручную менять не следует."
                ),
                verbose_name="Legacy-проект",
            ),
        ),
        migrations.AddField(
            model_name="constructionsite",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_sites",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Создан администратором",
            ),
        ),
        migrations.AddField(
            model_name="constructionsite",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name="Создан"),
            preserve_default=False,
        ),
        migrations.AlterModelOptions(
            name="constructionsite",
            options={"verbose_name": "Проект (площадка)", "verbose_name_plural": "Проекты (площадки)"},
        ),
        migrations.CreateModel(
            name="ProjectMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Добавлен")),
                (
                    "site",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="core.constructionsite",
                        verbose_name="Проект",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_memberships",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Участник проекта",
                "verbose_name_plural": "Участники проектов",
                "unique_together": {("site", "user")},
            },
        ),
        migrations.RunPython(pin_legacy_project, unpin_legacy_project),
    ]
