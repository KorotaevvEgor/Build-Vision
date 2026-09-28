"""Модели данных СтройКонтроль.

Всё, что раньше жило в YAML/JSON-конфигурации (словарь классов, правила,
демонстрационный график, геометрия площадки), теперь хранится здесь и
редактируется через Django admin. Результаты анализа снимков (Observation/
Detection/StageEvaluationRecord) также сохраняются сюда — это закрывает
требование ТЗ о хранении информации об отклонениях и нарушениях.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class ConstructionSite(models.Model):
    """Проект (строительная площадка). Геометрия — GeoJSON Polygon (без PostGIS).

    Исторически называлась «демонстрационной площадкой» — сейчас это единица
    проекта в экране «Проекты» (см. план «выбор и создание проектов»).
    У новых проектов геометрия/координаты могут отсутствовать до их настройки
    администратором через Django admin.
    """

    class Status(models.TextChoices):
        PREPARATION = "preparation", "Подготовка"
        CONSTRUCTION = "construction", "Строительство"
        PAUSED = "paused", "Приостановлен"
        COMPLETED = "completed", "Завершён"

    name = models.CharField("Название", max_length=200)
    external_key = models.SlugField(
        "Ключ импорта",
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "Заполняется только у объектов, загруженных командой импорта. Нужен, чтобы "
            "повторный импорт обновлял тот же объект, а не плодил дубликаты по названию."
        ),
    )
    address = models.CharField("Адрес", max_length=300, blank=True)
    status = models.CharField(
        "Статус проекта", max_length=16, choices=Status.choices, default=Status.CONSTRUCTION
    )
    latitude = models.FloatField("Широта (точка на карте)", null=True, blank=True)
    longitude = models.FloatField("Долгота (точка на карте)", null=True, blank=True)
    note = models.TextField(
        "Примечание",
        blank=True,
        help_text="Например: координаты вымышлены для демонстрации.",
    )
    is_demo = models.BooleanField("Демонстрационные данные", default=True)
    is_legacy = models.BooleanField(
        "Legacy-проект",
        default=False,
        help_text=(
            "Ровно один проект может быть закреплён как legacy — к нему обращаются старые "
            "/api/... маршруты для совместимости с уже установленным APK. Устанавливается один раз "
            "миграцией, вручную менять не следует."
        ),
    )
    boundary_geojson = models.JSONField(
        "Граница площадки (GeoJSON Polygon)",
        null=True,
        blank=True,
        help_text='{"type": "Polygon", "coordinates": [[[lon, lat], ...]]}. Пусто — граница ещё не задана.',
    )
    stream_url = models.URLField(
        "Ссылка на видеотрансляцию",
        blank=True,
        default="",
        help_text=(
            "Просто внешняя ссылка для просмотра (например, YouTube-трансляция). Система не "
            "обрабатывает сам видеопоток и не анализирует его кадры — только фотографии."
        ),
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sites",
        verbose_name="Создан администратором",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Проект (площадка)"
        verbose_name_plural = "Проекты (площадки)"

    def __str__(self) -> str:
        return self.name


class ProjectMembership(models.Model):
    """Доступ участника к конкретному проекту.

    Администраторы (UserProfile.role=admin) видят все проекты независимо от
    членства — эта таблица ограничивает только обычных участников (см. план
    «выбор и создание проектов», раздел «Данные и разграничение доступа»).
    """

    site = models.ForeignKey(
        ConstructionSite, on_delete=models.CASCADE, related_name="memberships", verbose_name="Проект"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="project_memberships", verbose_name="Пользователь"
    )
    created_at = models.DateTimeField("Добавлен", auto_now_add=True)

    class Meta:
        verbose_name = "Участник проекта"
        verbose_name_plural = "Участники проектов"
        unique_together = [("site", "user")]

    def __str__(self) -> str:
        return f"{self.user.username} → {self.site.name}"


class Zone(models.Model):
    """Рабочая зона на площадке."""

    class Kind(models.TextChoices):
        WORK = "work", "Рабочая зона"
        PARKING = "parking", "Стоянка и отстой техники"
        ENTRANCE = "entrance", "Въезд и выезд"
        DANGER = "danger", "Опасная зона"
        UNCONTROLLED = "uncontrolled", "Вне контроля"

    site = models.ForeignKey(
        ConstructionSite, on_delete=models.CASCADE, related_name="zones", verbose_name="Площадка"
    )
    external_id = models.SlugField(
        "Идентификатор зоны",
        max_length=64,
        unique=True,
        help_text='Используется в API и на фронтенде, например "zone-a".',
    )
    name = models.CharField("Название", max_length=200)
    kind = models.CharField(
        "Тип зоны",
        max_length=16,
        choices=Kind.choices,
        default=Kind.WORK,
        help_text=(
            "Справочный тип для карты площадки (не влияет на проверку техники по графику — "
            "та логика работает через отдельные зоны кадра камеры, см. FrameZone)."
        ),
    )
    description = models.TextField("Описание", blank=True)
    geometry_geojson = models.JSONField(
        "Геометрия зоны (GeoJSON Polygon)",
        help_text='{"type": "Polygon", "coordinates": [[[lon, lat], ...]]}',
    )

    class Meta:
        verbose_name = "Зона"
        verbose_name_plural = "Зоны"

    def __str__(self) -> str:
        return f"{self.name} ({self.external_id})"


class VocabularyClass(models.Model):
    """Класс техники словаря открытой детекции (YOLO-World)."""

    key = models.SlugField("Ключ класса", max_length=64, unique=True)
    label_ru = models.CharField("Название по-русски", max_length=100)
    prompts = models.JSONField(
        "Текстовые промпты (англ.)",
        default=list,
        help_text='Список строк, например ["excavator", "crawler excavator"].',
    )
    in_taxonomy = models.BooleanField(
        "Входит в таксономию ТЗ",
        default=True,
        help_text="Выключено — вспомогательный класс-«отвлекающий» (человек, легковой автомобиль).",
    )

    class Meta:
        verbose_name = "Класс техники"
        verbose_name_plural = "Словарь классов техники"
        ordering = ["key"]

    def __str__(self) -> str:
        return self.label_ru


class Stage(models.Model):
    """Этап графика строительно-монтажных работ.

    График сетевой, а не плоский список: у этапа есть родитель (заказчик
    работает с четырьмя уровнями детализации) и связи предшествования.
    Без этого нельзя ответить на главный вопрос стройки: сдвинет ли
    отставание по конкретной работе дату сдачи объекта или будет поглощено запасом.
    """

    external_id = models.SlugField("Идентификатор этапа", max_length=64, unique=True)
    zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="stages", verbose_name="Зона"
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="Родительская работа",
        help_text="Укрупнённая работа или веха, в которую входит этот этап.",
    )
    predecessors = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="successors",
        verbose_name="Предшественники",
        help_text=(
            "Работы, которые должны завершиться до начала этой — связь «окончание-начало». "
            "На них строится расчёт критического пути."
        ),
    )
    work_code = models.CharField(
        "Код работы (справочник)",
        max_length=32,
        blank=True,
        help_text="Код из works_catalog.csv, если есть свой; иначе — код родителя.",
    )
    work_name = models.CharField("Наименование работы", max_length=300)
    start_date = models.DateField("Начало")
    end_date = models.DateField("Окончание")
    technology_assumption = models.TextField(
        "Технологическое допущение",
        blank=True,
        help_text="Один из возможных вариантов технологии — не единственно допустимый.",
    )
    is_demo = models.BooleanField("Демонстрационные даты", default=True)

    class Meta:
        verbose_name = "Этап графика"
        verbose_name_plural = "Этапы графика"
        ordering = ["start_date"]

    def __str__(self) -> str:
        return f"{self.work_name} ({self.start_date:%d.%m.%Y}–{self.end_date:%d.%m.%Y})"


class StageRule(models.Model):
    """Правило соответствия техники этапу — отдельно от кода, редактируется в админке."""

    stage = models.OneToOneField(
        Stage, on_delete=models.CASCADE, related_name="rule", verbose_name="Этап"
    )
    required = models.ManyToManyField(
        VocabularyClass,
        through="StageRequiredItem",
        related_name="required_for_rules",
        blank=True,
        verbose_name="Обязательная техника",
    )
    allowed = models.ManyToManyField(
        VocabularyClass,
        related_name="allowed_for_rules",
        blank=True,
        verbose_name="Допустимая техника",
    )
    alternatives_note = models.TextField(
        "Примечание об альтернативах",
        blank=True,
        help_text="Например: другая согласованная технология не считается нарушением.",
    )

    class Meta:
        verbose_name = "Правило техники для этапа"
        verbose_name_plural = "Правила техники по этапам"

    def __str__(self) -> str:
        return f"Правило: {self.stage.work_name}"


class StageRequiredItem(models.Model):
    """Обязательная техника этапа с минимальным количеством (план для Plan vs Fact)."""

    stage_rule = models.ForeignKey(
        StageRule, on_delete=models.CASCADE, related_name="required_items", verbose_name="Правило"
    )
    vocabulary_class = models.ForeignKey(
        VocabularyClass, on_delete=models.CASCADE, related_name="required_items", verbose_name="Класс техники"
    )
    min_quantity = models.PositiveSmallIntegerField("Минимальное количество", default=1)

    class Meta:
        verbose_name = "Обязательная техника (количество)"
        verbose_name_plural = "Обязательная техника (количества)"
        unique_together = [("stage_rule", "vocabulary_class")]

    def __str__(self) -> str:
        return f"{self.vocabulary_class.label_ru} × {self.min_quantity}"


class Camera(models.Model):
    """Камера наблюдения, привязанная к зоне. Снимки анализируются вручную через загрузку."""

    zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="cameras", verbose_name="Зона"
    )
    external_id = models.SlugField("Идентификатор камеры", max_length=64, unique=True)
    name = models.CharField("Название", max_length=200)
    latitude = models.FloatField("Широта")
    longitude = models.FloatField("Долгота")
    stream_url = models.URLField(
        "Ссылка на видеотрансляцию",
        blank=True,
        default="",
        help_text=(
            "Просто внешняя ссылка для просмотра этой конкретной камеры. Система не обрабатывает сам поток и не анализирует его кадры — только фотографии."
        ),
    )
    is_demo = models.BooleanField("Демонстрационные данные", default=True)
    note = models.TextField(
        "Примечание",
        blank=True,
        help_text="Например: координаты — центроид зоны, а не реальное расположение камеры.",
    )

    class Meta:
        verbose_name = "Камера"
        verbose_name_plural = "Камеры"

    def __str__(self) -> str:
        return f"{self.name} ({self.zone.name})"


class FrameZone(models.Model):
    """Зона, размеченная прямо на кадре камеры, в пиксельных координатах.

    Отличается от `Zone` принципиально. `Zone` — это участок площадки на
    карте в географических координатах, к нему привязаны этапы графика.
    `FrameZone` — это область внутри изображения конкретной камеры, и только она
    позволяет ответить на вопрос, работает ли техника или простаивает: экскаватор
    в рабочей зоне котлована и тот же экскаватор у въезда — разные ситуации.

    Способ подсказан самими постановщиками задачи: определять факт работы и
    простоя по тому, в какой зоне техника находится на снимке.
    """

    class Kind(models.TextChoices):
        WORK = "work", "Рабочая зона"
        PARKING = "parking", "Стоянка и отстой техники"
        ENTRANCE = "entrance", "Въезд и выезд"
        DANGER = "danger", "Опасная зона"
        UNCONTROLLED = "uncontrolled", "Вне контроля"

    camera = models.ForeignKey(
        "Camera", on_delete=models.CASCADE, related_name="frame_zones", verbose_name="Камера"
    )
    name = models.CharField("Название", max_length=200)
    kind = models.CharField("Тип зоны", max_length=16, choices=Kind.choices, default=Kind.WORK)
    stage = models.ForeignKey(
        "Stage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="frame_zones",
        verbose_name="Этап графика",
        help_text="Для рабочей зоны: какой этап ведётся именно здесь.",
    )
    polygon = models.JSONField(
        "Полигон в пикселях кадра",
        help_text="Список точек [[x, y], ...] в координатах опорного кадра, минимум три точки.",
    )
    reference_width = models.PositiveIntegerField(
        "Ширина опорного кадра",
        help_text=(
            "Размер снимка, на котором рисовалась зона. Нужен, чтобы пересчитать "
            "координаты, если камера прислала кадр другого разрешения."
        ),
    )
    reference_height = models.PositiveIntegerField("Высота опорного кадра")
    note = models.TextField("Примечание", blank=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Изменена", auto_now=True)

    class Meta:
        verbose_name = "Зона на кадре"
        verbose_name_plural = "Зоны на кадре"
        ordering = ["camera", "kind", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_kind_display()}, {self.camera.name})"


class UserProfile(models.Model):
    """Роль и должность пользователя. Поверх стандартной модели User Django."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Администратор"
        PARTICIPANT = "participant", "Участник проекта"

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="profile", verbose_name="Пользователь"
    )
    role = models.CharField("Роль", max_length=16, choices=Role.choices, default=Role.PARTICIPANT)
    position = models.CharField(
        "Должность",
        max_length=150,
        blank=True,
        help_text="Отображается в шапке интерфейса под именем, например «Ruководитель проекта».",
    )
    avatar_path = models.CharField(
        "Путь к файлу аватара",
        max_length=500,
        blank=True,
        default="",
        help_text="Абсолютный путь на диске (data/uploads/avatars/...), не URL — отдаётся через отдельный эндпоинт FastAPI.",
    )

    class Meta:
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    def __str__(self) -> str:
        return f"{self.user.get_full_name() or self.user.username} — {self.get_role_display()}"

    @property
    def display_position(self) -> str:
        """Должность для шапки интерфейса; если не заполнена — читаемое название роли."""
        return self.position or self.get_role_display()


class ConfusablePair(models.Model):
    """Известная путаемая пара классов (см. отчёт о качестве детектора)."""

    class_a = models.ForeignKey(
        VocabularyClass, on_delete=models.CASCADE, related_name="confusable_as_a", verbose_name="Класс А"
    )
    class_b = models.ForeignKey(
        VocabularyClass, on_delete=models.CASCADE, related_name="confusable_as_b", verbose_name="Класс Б"
    )
    evidence_note = models.TextField(
        "Обоснование", blank=True, help_text="Например: ссылка на конкретный снимок из val-выборки."
    )

    class Meta:
        verbose_name = "Путаемая пара классов"
        verbose_name_plural = "Путаемые пары классов"
        unique_together = [("class_a", "class_b")]

    def __str__(self) -> str:
        return f"{self.class_a.label_ru} ↔ {self.class_b.label_ru}"


class KnownLimitation(models.Model):
    """Измеренное ограничение качества, не покрываемое механизмом confusable-пар."""

    class Issue(models.TextChoices):
        LOW_PRECISION = "low_precision", "Низкая точность"
        LOW_RECALL = "low_recall", "Низкая полнота"

    vocabulary_class = models.ForeignKey(
        VocabularyClass, on_delete=models.CASCADE, related_name="known_limitations", verbose_name="Класс"
    )
    issue = models.CharField("Тип проблемы", max_length=20, choices=Issue.choices)
    description = models.TextField("Описание")

    class Meta:
        verbose_name = "Известное ограничение"
        verbose_name_plural = "Известные ограничения"

    def __str__(self) -> str:
        return f"{self.vocabulary_class.label_ru}: {self.get_issue_display()}"


class WeatherRule(models.Model):
    """Погодное правило риска для этапа."""

    class Factor(models.TextChoices):
        TEMPERATURE = "temperature_2m", "Температура"
        PRECIPITATION = "precipitation", "Осадки"
        PRECIPITATION_PROBABILITY = "precipitation_probability", "Вероятность осадков"
        WIND_SPEED = "wind_speed_10m", "Скорость ветра"
        WIND_GUSTS = "wind_gusts_10m", "Порывы ветра"

    class Comparison(models.TextChoices):
        GTE = "gte", "не меньше (≥)"
        LTE = "lte", "не больше (≤)"

    stage = models.ForeignKey(
        Stage, on_delete=models.CASCADE, related_name="weather_rules", verbose_name="Этап"
    )
    factor = models.CharField("Фактор", max_length=32, choices=Factor.choices)
    comparison = models.CharField("Сравнение", max_length=8, choices=Comparison.choices)
    threshold = models.FloatField("Порог")
    units = models.CharField("Единицы", max_length=16, blank=True)
    message = models.TextField("Сообщение для инженера")

    class Meta:
        verbose_name = "Погодное правило"
        verbose_name_plural = "Погодные правила"

    def __str__(self) -> str:
        return f"{self.stage.work_name}: {self.get_factor_display()}"


class Observation(models.Model):
    """Результат анализа одного снимка — центральная запись истории."""

    class Status(models.TextChoices):
        NO_DEVIATION = "no_deviation", "Отклонений не выявлено"
        POSSIBLE_DEVIATION = "possible_deviation", "Возможное отклонение"
        INSUFFICIENT_DATA = "insufficient_data", "Недостаточно данных"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zone = models.ForeignKey(
        Zone, on_delete=models.PROTECT, related_name="observations", verbose_name="Зона"
    )
    camera = models.ForeignKey(
        "Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="observations",
        verbose_name="Камера",
        help_text=(
            "Без привязки к камере невозможно ни применить зоны кадра, ни сравнить "
            "снимок с предыдущими: кадры разных камер несопоставимы попиксельно."
        ),
    )
    image_width = models.PositiveIntegerField("Ширина снимка", null=True, blank=True)
    image_height = models.PositiveIntegerField("Высота снимка", null=True, blank=True)
    image_path = models.CharField("Путь к файлу снимка", max_length=500)
    image_sha256 = models.CharField("SHA-256 снимка", max_length=64, db_index=True)
    observed_date = models.DateField("Дата съёмки", null=True, blank=True)
    date_confirmed = models.BooleanField("Дата подтверждена", default=False)
    overall_status = models.CharField("Итоговый статус", max_length=24, choices=Status.choices)
    overall_explanation = models.TextField("Объяснение")

    # Оценка по самой фотографии — второй, независимый от детектора источник.
    # Хранится именно здесь, а не считается каждый раз заново: без сохранённой
    # готовности невозможна кривая готовности объекта во времени, а именно она
    # показывает надзору отставание одним взглядом.
    vision_stage_key = models.CharField(
        "Стадия по снимку (ключ)", max_length=32, blank=True, default=""
    )
    vision_stage_label = models.CharField(
        "Стадия по снимку", max_length=120, blank=True, default=""
    )
    readiness_percent = models.PositiveSmallIntegerField(
        "Готовность объекта по снимку, %",
        null=True,
        blank=True,
        validators=[MaxValueValidator(100)],
        help_text="Пусто — модель не смогла оценить готовность по этому кадру.",
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Наблюдение (анализ снимка)"
        verbose_name_plural = "Наблюдения (история анализа)"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.zone.name} — {self.created_at:%d.%m.%Y %H:%M}"


class Detection(models.Model):
    """Одна обнаруженная рамка на снимке."""

    observation = models.ForeignKey(
        Observation, on_delete=models.CASCADE, related_name="detections", verbose_name="Наблюдение"
    )
    class_key = models.CharField("Класс (ключ)", max_length=64)
    label_ru = models.CharField("Класс (по-русски)", max_length=100)
    in_taxonomy = models.BooleanField("Входит в таксономию", default=True)
    confidence = models.FloatField("Уверенность")
    bbox = models.JSONField("Рамка [x1, y1, x2, y2]")
    ambiguous = models.BooleanField("Неоднозначная классификация", default=False)
    runner_up_class_key = models.CharField(
        "Альтернативный класс (при неоднозначности)", max_length=64, blank=True
    )

    frame_zone = models.ForeignKey(
        "FrameZone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="detections",
        verbose_name="Зона на кадре",
        help_text="Зона, в которую попадает нижняя точка рамки (точка опоры машины).",
    )

    class Activity(models.TextChoices):
        WORKING = "working", "Работает"
        IDLE = "idle", "Простаивает"
        UNKNOWN = "unknown", "Определить нельзя"

    activity = models.CharField(
        "Активность",
        max_length=8,
        choices=Activity.choices,
        default=Activity.UNKNOWN,
    )
    activity_reason = models.CharField(
        "Обоснование активности",
        max_length=300,
        blank=True,
        help_text="Почему техника считается работающей или простаивающей — для объяснения инженеру.",
    )

    class Meta:
        verbose_name = "Детекция"
        verbose_name_plural = "Детекции"

    def __str__(self) -> str:
        return f"{self.label_ru} ({self.confidence:.2f})"


class StageEvaluationRecord(models.Model):
    """Результат проверки одного этапа в рамках наблюдения."""

    observation = models.ForeignKey(
        Observation, on_delete=models.CASCADE, related_name="stage_evaluations", verbose_name="Наблюдение"
    )
    stage = models.ForeignKey(
        Stage, on_delete=models.SET_NULL, null=True, related_name="evaluations", verbose_name="Этап"
    )
    work_name_snapshot = models.CharField("Название этапа на момент проверки", max_length=300)
    status = models.CharField("Статус", max_length=24, choices=Observation.Status.choices)
    explanation = models.TextField("Объяснение")
    required_snapshot = models.JSONField("Требуемая техника (снимок)", default=list)
    allowed_snapshot = models.JSONField("Допустимая техника (снимок)", default=list)
    quantity_checks_snapshot = models.JSONField(
        "План/факт по количеству (снимок)",
        default=list,
        help_text='[{"class_key", "label_ru", "required_qty", "actual_qty", "satisfied"}, ...]',
    )
    missing_required = models.JSONField("Отсутствующая техника", default=list)
    unexpected_detections = models.JSONField("Неожиданная техника", default=list)
    ambiguous_detections = models.JSONField("Неоднозначные детекции", default=list)

    class Meta:
        verbose_name = "Результат проверки этапа"
        verbose_name_plural = "Результаты проверки этапов"

    def __str__(self) -> str:
        return f"{self.work_name_snapshot}: {self.get_status_display()}"


class Deviation(models.Model):
    """Отклонение с собственной судьбой, а не запись в ленте.

    До этой модели отклонение существовало только как статус отдельного снимка:
    одна и та же нехватка техники на десяти кадрах подряд давала десять
    одинаковых записей, и нельзя было ответить, устранено ли что-нибудь.
    Теперь одно и то же нарушение — одна запись с историей: выявлено, назначено,
    устранено, подтверждено. Снимок «до» — кадр, на котором отклонение выявлено,
    снимок «после» — следующий кадр той же зоны, где оно уже не воспроизводится;
    его не нужно прикреплять руками, он находится сам.
    """

    class Kind(models.TextChoices):
        MISSING_EQUIPMENT = "missing_equipment", "Нет требуемой техники"
        QUANTITY_SHORTFALL = "quantity_shortfall", "Техники меньше плана"
        UNEXPECTED_EQUIPMENT = "unexpected_equipment", "Посторонняя техника"
        EQUIPMENT_IDLE = "equipment_idle", "Простой техники"
        EQUIPMENT_IN_DANGER_ZONE = "equipment_in_danger_zone", "Техника в опасной зоне"
        EQUIPMENT_OUT_OF_WORK_ZONE = "equipment_out_of_work_zone", "Техника вне рабочей зоны"
        ZONE_NOT_COVERED = "zone_not_covered", "Зона вне контроля камер"
        STAGE_MISMATCH = "stage_mismatch", "Стадия на снимке не совпадает с графиком"

    class Severity(models.TextChoices):
        CRITICAL = "critical", "Критично"
        WARNING = "warning", "Требует внимания"
        INFO = "info", "К сведению"

    class Status(models.TextChoices):
        DETECTED = "detected", "Выявлено"
        ASSIGNED = "assigned", "Назначено"
        RESOLVED = "resolved", "Устранено"
        CONFIRMED = "confirmed", "Подтверждено"
        DISMISSED = "dismissed", "Ложное срабатывание"

    #: Статусы, при которых отклонение считается открытым и может повториться на следующем кадре.
    OPEN_STATUSES = (Status.DETECTED, Status.ASSIGNED)

    zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name="deviations", verbose_name="Зона"
    )
    stage = models.ForeignKey(
        Stage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deviations",
        verbose_name="Этап графика",
    )
    kind = models.CharField("Тип", max_length=32, choices=Kind.choices)
    severity = models.CharField(
        "Важность", max_length=16, choices=Severity.choices, default=Severity.WARNING
    )
    status = models.CharField(
        "Состояние", max_length=16, choices=Status.choices, default=Status.DETECTED
    )
    signature = models.CharField(
        "Ключ совпадения",
        max_length=300,
        db_index=True,
        help_text=(
            "Устойчивый ключ (зона + этап + тип + состав техники). По нему система понимает, "
            "что на новом снимке то же самое нарушение, а не новое."
        ),
    )
    title = models.CharField("Заголовок", max_length=300)
    message = models.TextField("Описание")
    equipment = models.JSONField("Затронутая техника", default=list, blank=True)
    is_on_critical_path = models.BooleanField(
        "На критическом пути",
        default=False,
        help_text="Отклонение по такому этапу напрямую сдвигает дату сдачи объекта.",
    )

    first_observation = models.ForeignKey(
        Observation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deviations_opened",
        verbose_name="Снимок «до» (выявлено)",
    )
    last_observation = models.ForeignKey(
        Observation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deviations_seen",
        verbose_name="Последний снимок с этим отклонением",
    )
    resolved_observation = models.ForeignKey(
        Observation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deviations_closed",
        verbose_name="Снимок «после» (устранено)",
    )
    occurrence_count = models.PositiveIntegerField("Сколько снимков подтвердили", default=1)

    assignee = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_deviations",
        verbose_name="Ответственный",
    )
    resolution_note = models.TextField("Комментарий при закрытии", blank=True)
    auto_resolved = models.BooleanField(
        "Закрыто автоматически",
        default=False,
        help_text="На следующем снимке зоны отклонение больше не воспроизвелось.",
    )

    detected_at = models.DateTimeField("Выявлено", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)
    resolved_at = models.DateTimeField("Устранено", null=True, blank=True)
    confirmed_at = models.DateTimeField("Подтверждено", null=True, blank=True)

    class Meta:
        verbose_name = "Отклонение"
        verbose_name_plural = "Отклонения"
        ordering = ["-detected_at"]
        indexes = [models.Index(fields=["zone", "status"])]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_status_display()})"


class ProjectEvent(models.Model):
    """Журнал событий проекта — единая лента того, что происходило.

    Статусы и агрегаты показывают состояние на сейчас, но не отвечают на вопрос
    «когда и почему стало так». Журнал отвечает: снимок загружен, отклонение
    выявлено, отклонение закрыто следующим кадром, ответственный назначен.
    """

    class Kind(models.TextChoices):
        OBSERVATION_ANALYZED = "observation_analyzed", "Снимок проанализирован"
        DEVIATION_DETECTED = "deviation_detected", "Отклонение выявлено"
        DEVIATION_REPEATED = "deviation_repeated", "Отклонение повторилось"
        DEVIATION_STATUS_CHANGED = "deviation_status_changed", "Состояние отклонения изменено"
        DEVIATION_AUTO_RESOLVED = "deviation_auto_resolved", "Отклонение закрыто по следующему снимку"

    site = models.ForeignKey(
        ConstructionSite, on_delete=models.CASCADE, related_name="events", verbose_name="Проект"
    )
    kind = models.CharField("Тип события", max_length=32, choices=Kind.choices)
    title = models.CharField("Заголовок", max_length=300)
    message = models.TextField("Описание", blank=True)
    old_value = models.CharField("Было", max_length=100, blank=True)
    new_value = models.CharField("Стало", max_length=100, blank=True)
    zone = models.ForeignKey(
        Zone, on_delete=models.SET_NULL, null=True, blank=True, related_name="events", verbose_name="Зона"
    )
    observation = models.ForeignKey(
        Observation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        verbose_name="Наблюдение",
    )
    deviation = models.ForeignKey(
        Deviation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        verbose_name="Отклонение",
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="project_events",
        verbose_name="Кто сделал",
        help_text="Пусто — событие создано системой по результату анализа снимка.",
    )
    created_at = models.DateTimeField("Когда", auto_now_add=True)

    class Meta:
        verbose_name = "Событие проекта"
        verbose_name_plural = "Лента событий"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.title}"


class Correction(models.Model):
    """Исправление инженера по одной детекции — обучающий пример для
    классификатора-корректора (см. модуль «AI Learning» в плане).

    Единственный в проекте реально размеченный человеком датасет: у исходных
    100 снимков (data/config/splits.json) нет разметки классов, поэтому
    именно коррекции инженера — источник истинных меток для обучения и
    честной оценки качества классификатора (train/test-разбиение внутри них).
    """

    observation = models.ForeignKey(
        Observation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corrections",
        verbose_name="Наблюдение",
    )
    crop_image_path = models.CharField("Путь к обрезанному фрагменту", max_length=500)
    bbox = models.JSONField("Рамка [x1, y1, x2, y2] на исходном снимке", default=list)
    original_class_key = models.CharField("Исходный класс (по версии детектора)", max_length=64, blank=True)
    original_confidence = models.FloatField("Исходная уверенность", null=True, blank=True)
    corrected_class = models.ForeignKey(
        VocabularyClass,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corrections",
        verbose_name="Исправленный класс (пусто — «не техника»)",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corrections",
        verbose_name="Автор коррекции",
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Коррекция"
        verbose_name_plural = "Коррекции"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        target = self.corrected_class.label_ru if self.corrected_class else "не техника"
        return f"{self.original_class_key or '?'} → {target}"


class ModelVersion(models.Model):
    """Версия классификатора-корректора поверх CLIP-эмбеддингов.

    metrics_json хранит только реально измеренные значения на отложенной
    части накопленных коррекций — в датасете проекта нет отдельного
    размеченного held-out набора (см. Correction), поэтому «эталонной»
    внешней выборки для валидации не существует.
    """

    class Status(models.TextChoices):
        CANDIDATE = "candidate", "Кандидат"
        PRODUCTION = "production", "Рабочая версия"
        ARCHIVED = "archived", "Архив"

    version_label = models.CharField("Версия", max_length=32)
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.CANDIDATE)
    artifact_path = models.CharField("Путь к артефакту классификатора", max_length=500, blank=True)
    trained_at = models.DateTimeField("Обучена", null=True, blank=True)
    training_sample_count = models.PositiveIntegerField("Число коррекций, использованных при обучении", default=0)
    metrics_json = models.JSONField(
        "Метрики (измеренные на отложенной части коррекций)",
        default=dict,
        blank=True,
        help_text='{"available": bool, "train_count", "test_count", "accuracy", "per_class": [...]}',
    )
    based_on = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derived_versions",
        verbose_name="Предыдущая версия",
    )
    notes = models.TextField("Примечание", blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Версия модели-корректора"
        verbose_name_plural = "Версии модели-корректора"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.version_label} ({self.get_status_display()})"


class MatchingSettings(models.Model):
    """Единственная запись глобальных настроек ядра сопоставления."""

    class VlmConfidence(models.TextChoices):
        HIGH = "high", "Только высокая"
        MEDIUM = "medium", "Высокая и средняя"
        LOW = "low", "Любая"

    ambiguity_margin = models.FloatField(
        "Порог неоднозначности",
        default=0.15,
        help_text=(
            "Справочно: для известных confusable-пар результат всегда считается "
            "неоднозначным независимо от confidence (см. detector.py) — это поле сейчас "
            "хранится для справки и будущей калибровки."
        ),
    )

    detector_confidence = models.FloatField(
        "Порог уверенности детектора",
        default=0.25,
        validators=[MinValueValidator(0.05), MaxValueValidator(0.95)],
        help_text=(
            "Рамки с меньшей уверенностью отбрасываются при анализе снимка. "
            "Ниже порог — больше находок и больше ложных срабатываний, выше — наоборот. "
            "Допустимый диапазон 0.05-0.95."
        ),
    )

    autolabel_min_vlm_confidence = models.CharField(
        "Минимальная уверенность при авторазметке",
        max_length=8,
        choices=VlmConfidence.choices,
        default=VlmConfidence.HIGH,
        help_text=(
            "Какой уверенности модели достаточно, чтобы принять класс фрагмента в разметку. "
            "«Только высокая» даёт меньше рамок, но меньше ошибок вроде «провод — это рукав "
            "бетононасоса» или «легковая машина — это грузовик»."
        ),
    )

    class Meta:
        verbose_name = "Настройки сопоставления"
        verbose_name_plural = "Настройки сопоставления"

    def __str__(self) -> str:
        return "Глобальные настройки сопоставления"

    @classmethod
    def get_solo(cls) -> MatchingSettings:
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class WeatherRiskRecord(models.Model):
    """Сохранённый период погодного риска (снимок на момент запроса)."""

    stage = models.ForeignKey(
        Stage, on_delete=models.CASCADE, related_name="weather_risk_records", verbose_name="Этап"
    )
    provider = models.CharField("Источник", max_length=64, default="open-meteo")
    factor = models.CharField("Фактор", max_length=32)
    comparison = models.CharField("Сравнение", max_length=8)
    threshold = models.FloatField("Порог")
    units = models.CharField("Единицы", max_length=16, blank=True)
    start_time_utc = models.DateTimeField("Начало периода (UTC)")
    end_time_utc = models.DateTimeField("Окончание периода (UTC)")
    peak_value = models.FloatField("Пиковое значение")
    message = models.TextField("Сообщение")
    fetched_at = models.DateTimeField("Получено", auto_now_add=True)

    class Meta:
        verbose_name = "Погодный риск (история)"
        verbose_name_plural = "Погодные риски (история)"
        ordering = ["-fetched_at"]

    def __str__(self) -> str:
        return f"{self.stage.work_name}: {self.factor} {self.start_time_utc:%d.%m %H:%M}"
