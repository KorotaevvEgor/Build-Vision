"""Django admin: полное редактирование справочников, правил и истории анализа."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import (
    Camera,
    ConfusablePair,
    ConstructionSite,
    Correction,
    Detection,
    Deviation,
    KnownLimitation,
    MatchingSettings,
    ModelVersion,
    Observation,
    ProjectEvent,
    ProjectMembership,
    Stage,
    StageEvaluationRecord,
    StageRequiredItem,
    StageRule,
    UserProfile,
    VocabularyClass,
    WeatherRiskRecord,
    WeatherRule,
    Zone,
)


class ZoneInline(admin.TabularInline):
    model = Zone
    extra = 0
    fields = ("external_id", "name", "description")
    show_change_link = True


class ProjectMembershipInline(admin.TabularInline):
    """Назначение участников на проект — участники без членства проект не видят.
    Администраторы видят все проекты независимо от этой таблицы."""

    model = ProjectMembership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(ConstructionSite)
class ConstructionSiteAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "status", "is_legacy", "is_demo")
    list_filter = ("status", "is_legacy", "is_demo")
    search_fields = ("name", "address")
    readonly_fields = ("is_legacy", "created_by", "created_at")
    inlines = [ProjectMembershipInline, ZoneInline]


class StageInline(admin.TabularInline):
    model = Stage
    extra = 0
    fields = ("external_id", "work_name", "start_date", "end_date", "is_demo")
    show_change_link = True


class CameraInline(admin.TabularInline):
    model = Camera
    extra = 0
    fields = ("external_id", "name", "latitude", "longitude", "is_demo")
    show_change_link = True


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "external_id", "site")
    list_filter = ("site",)
    search_fields = ("name", "external_id")
    inlines = [StageInline, CameraInline]


@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = ("name", "external_id", "zone", "latitude", "longitude", "is_demo")
    list_filter = ("zone", "is_demo")
    search_fields = ("name", "external_id")


@admin.register(VocabularyClass)
class VocabularyClassAdmin(admin.ModelAdmin):
    list_display = ("label_ru", "key", "in_taxonomy", "prompts_preview")
    list_filter = ("in_taxonomy",)
    search_fields = ("key", "label_ru")

    @admin.display(description="Промпты")
    def prompts_preview(self, obj: VocabularyClass) -> str:
        return ", ".join(obj.prompts[:3]) + ("…" if len(obj.prompts) > 3 else "")


class WeatherRuleInline(admin.TabularInline):
    model = WeatherRule
    extra = 0


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = (
        "work_name",
        "external_id",
        "zone",
        "parent",
        "start_date",
        "end_date",
        "predecessors_preview",
        "is_demo",
    )
    list_filter = ("zone", "is_demo")
    search_fields = ("work_name", "external_id", "work_code")
    date_hierarchy = "start_date"
    # Связи предшествования редактируются вручную чаще всего при перепланировке,
    # поэтому им нужен удобный виджет, а не список с Ctrl-кликом.
    filter_horizontal = ("predecessors",)
    autocomplete_fields = ("parent",)
    inlines = [WeatherRuleInline]

    @admin.display(description="Предшественники")
    def predecessors_preview(self, obj: Stage) -> str:
        return ", ".join(item.work_name for item in obj.predecessors.all()) or "—"


class StageRequiredItemInline(admin.TabularInline):
    """Обязательная техника этапа с количеством — план для таблицы Plan vs Fact."""

    model = StageRequiredItem
    extra = 1
    fields = ("vocabulary_class", "min_quantity")


@admin.register(StageRule)
class StageRuleAdmin(admin.ModelAdmin):
    list_display = ("stage", "required_preview", "allowed_preview")
    filter_horizontal = ("allowed",)
    search_fields = ("stage__work_name",)
    inlines = [StageRequiredItemInline]

    @admin.display(description="Обязательная техника")
    def required_preview(self, obj: StageRule) -> str:
        return ", ".join(
            f"{item.vocabulary_class.label_ru} ×{item.min_quantity}"
            for item in obj.required_items.select_related("vocabulary_class")
        )

    @admin.display(description="Допустимая техника")
    def allowed_preview(self, obj: StageRule) -> str:
        return ", ".join(c.label_ru for c in obj.allowed.all())


@admin.register(Deviation)
class DeviationAdmin(admin.ModelAdmin):
    """Отклонения с историей состояний — главный рабочий список стройконтроля."""

    list_display = (
        "title",
        "zone",
        "severity",
        "status",
        "is_on_critical_path",
        "occurrence_count",
        "auto_resolved",
        "detected_at",
    )
    list_filter = ("status", "severity", "kind", "is_on_critical_path", "auto_resolved", "zone")
    search_fields = ("title", "message", "signature")
    date_hierarchy = "detected_at"
    # Снимки «до/после» и ключ совпадения ставит система: правка руками
    # разорвала бы связь отклонения с доказательствами.
    readonly_fields = (
        "signature",
        "first_observation",
        "last_observation",
        "resolved_observation",
        "occurrence_count",
        "detected_at",
        "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        # Отклонения создаются анализом снимка, вручную — нет.
        return False


@admin.register(ProjectEvent)
class ProjectEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "site", "kind", "title", "actor")
    list_filter = ("kind", "site")
    search_fields = ("title", "message")
    date_hierarchy = "created_at"
    readonly_fields = tuple(
        field.name for field in ProjectEvent._meta.fields if field.name != "id"
    )

    def has_add_permission(self, request) -> bool:
        # Журнал пишется системой; запись вручную сделала бы его недостоверным.
        return False


@admin.register(ConfusablePair)
class ConfusablePairAdmin(admin.ModelAdmin):
    list_display = ("class_a", "class_b", "evidence_note")
    search_fields = ("class_a__label_ru", "class_b__label_ru")


@admin.register(KnownLimitation)
class KnownLimitationAdmin(admin.ModelAdmin):
    list_display = ("vocabulary_class", "issue", "description")
    list_filter = ("issue",)


@admin.register(WeatherRule)
class WeatherRuleAdmin(admin.ModelAdmin):
    list_display = ("stage", "factor", "comparison", "threshold", "units")
    list_filter = ("factor", "comparison")


class DetectionInline(admin.TabularInline):
    model = Detection
    extra = 0
    fields = ("class_key", "label_ru", "confidence", "ambiguous", "in_taxonomy", "runner_up_class_key")
    readonly_fields = fields


class StageEvaluationInline(admin.StackedInline):
    model = StageEvaluationRecord
    extra = 0
    fields = (
        "stage",
        "work_name_snapshot",
        "status",
        "explanation",
        "required_snapshot",
        "allowed_snapshot",
        "missing_required",
        "unexpected_detections",
        "ambiguous_detections",
    )
    readonly_fields = fields


@admin.register(Observation)
class ObservationAdmin(admin.ModelAdmin):
    """История анализа — главный экран для просмотра результатов работы сервиса."""

    list_display = (
        "created_at",
        "zone",
        "overall_status",
        "observed_date",
        "date_confirmed",
        "image_sha256_short",
    )
    list_filter = ("overall_status", "date_confirmed", "zone")
    search_fields = ("image_sha256", "image_path")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "image_sha256", "image_path", "created_at")
    inlines = [DetectionInline, StageEvaluationInline]

    @admin.display(description="SHA-256")
    def image_sha256_short(self, obj: Observation) -> str:
        return obj.image_sha256[:12] + "…"

    def has_add_permission(self, request) -> bool:
        # Наблюдения создаются только через API анализа снимка, не вручную.
        return False


@admin.register(MatchingSettings)
class MatchingSettingsAdmin(admin.ModelAdmin):
    list_display = ("ambiguity_margin",)

    def has_add_permission(self, request) -> bool:
        return not MatchingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(WeatherRiskRecord)
class WeatherRiskRecordAdmin(admin.ModelAdmin):
    list_display = ("stage", "factor", "peak_value", "start_time_utc", "end_time_utc", "fetched_at")
    list_filter = ("factor", "stage")
    date_hierarchy = "fetched_at"

    def has_add_permission(self, request) -> bool:
        return False


class UserProfileInline(admin.StackedInline):
    """Роль (Администратор/Участник проекта) и должность — прямо в карточке пользователя."""

    model = UserProfile
    can_delete = False
    verbose_name_plural = "Роль и должность (BuildVision)"


class BuildVisionUserAdmin(UserAdmin):
    inlines = (*UserAdmin.inlines, UserProfileInline)
    list_display = (*UserAdmin.list_display, "role_display")

    @admin.display(description="Роль")
    def role_display(self, obj: User) -> str:
        profile = getattr(obj, "profile", None)
        return profile.get_role_display() if profile else "—"


admin.site.unregister(User)
admin.site.register(User, BuildVisionUserAdmin)


@admin.register(Correction)
class CorrectionAdmin(admin.ModelAdmin):
    """Коррекции создаются только через API («Что это?» в интерфейсе), не вручную."""

    list_display = (
        "created_at",
        "original_class_key",
        "corrected_class",
        "original_confidence",
        "created_by",
        "observation",
    )
    list_filter = ("corrected_class",)
    search_fields = ("original_class_key",)
    readonly_fields = (
        "observation",
        "crop_image_path",
        "bbox",
        "original_class_key",
        "original_confidence",
        "created_by",
        "created_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    """Версии создаются через POST /api/model-versions/train, статус меняется через /deploy."""

    list_display = (
        "version_label",
        "status",
        "trained_at",
        "training_sample_count",
        "created_at",
    )
    list_filter = ("status",)
    readonly_fields = (
        "artifact_path",
        "trained_at",
        "training_sample_count",
        "metrics_json",
        "based_on",
        "created_at",
    )

    def has_add_permission(self, request) -> bool:
        return False
