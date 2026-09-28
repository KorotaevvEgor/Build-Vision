"""Чтение зон кадра и истории снимков камеры.

Отделено от `activity.py` намеренно: там чистая геометрия и правила, которые
тестируются без базы данных, здесь — доступ к Django ORM. Благодаря этому
логику определения простоя можно проверить на выдуманных координатах, не
поднимая ни базу, ни камеры.

При недоступной базе возвращаются пустые списки: анализ снимка обязан
продолжать работать, просто без определения активности.
"""

from __future__ import annotations

import logging

from . import django_bridge

logger = logging.getLogger(__name__)

# Сколько предыдущих снимков камеры поднимать для сравнения. Больше трёх не
# нужно: решение о простое принимается по двум кадрам, третий — запас на случай,
# если на одном из них машина не была распознана.
HISTORY_DEPTH = 3

# Максимальный разрыв между снимками, при котором их вообще осмысленно
# сравнивать попиксельно. Правило «машина не сдвинулась» построено на том, что
# камеры снимают раз в 20-30 минут. На кадрах с разницей в месяц оно превращается
# в абсурд: две разные машины, случайно оказавшиеся в одном месте в разные месяцы,
# были бы объявлены простаивающей техникой. Сутки — заведомо безопасный запас
# над реальным интервалом съёмки.
MAX_COMPARABLE_GAP_DAYS = 1


def load_frame_zones(camera_external_id: str | None) -> list[dict]:
    """Зоны, размеченные на кадре указанной камеры."""
    if not camera_external_id or not django_bridge.ensure_django_ready():
        return []
    try:
        from core.models import FrameZone

        rows = FrameZone.objects.filter(camera__external_id=camera_external_id).select_related("stage")
        return [
            {
                "id": row.pk,
                "name": row.name,
                "kind": row.kind,
                "polygon": row.polygon,
                "reference_width": row.reference_width,
                "reference_height": row.reference_height,
                "stage_id": row.stage.external_id if row.stage else None,
            }
            for row in rows
        ]
    except Exception:
        logger.exception("Не удалось прочитать зоны кадра")
        return []


def load_previous_frames(
    camera_external_id: str | None,
    depth: int = HISTORY_DEPTH,
    observed_date=None,
) -> list[list[dict]]:
    """Детекции предыдущих снимков той же камеры, от самого свежего к старым.

    Сравнивать можно только кадры одной камеры: у разных камер разный ракурс,
    и одинаковые пиксельные координаты означают совершенно разные места.

    И только близкие по времени кадры: если у текущего снимка есть подтверждённая
    дата, история ограничивается окном ``MAX_COMPARABLE_GAP_DAYS``. Без этого на
    архивной съёмке раз в месяц правило простоя давало бы уверенную чушь.
    """
    if not camera_external_id or not django_bridge.ensure_django_ready():
        return []
    try:
        from datetime import timedelta

        from core.models import Observation

        queryset = Observation.objects.filter(camera__external_id=camera_external_id)
        if observed_date is not None:
            window_start = observed_date - timedelta(days=MAX_COMPARABLE_GAP_DAYS)
            queryset = queryset.filter(
                observed_date__isnull=False,
                observed_date__gte=window_start,
                observed_date__lte=observed_date,
            )

        observations = queryset.order_by("-created_at").prefetch_related("detections")[:depth]
        return [
            [
                {"class_key": detection.class_key, "bbox": detection.bbox}
                for detection in observation.detections.all()
            ]
            for observation in observations
        ]
    except Exception:
        logger.exception("Не удалось прочитать историю снимков камеры")
        return []


def uncovered_stage_zones(site=None) -> list[str]:
    """Зоны графика, которые не покрыты ни одной рабочей зоной на кадрах камер.

    Постановщики прямо просили предупреждать, что часть площадки находится вне
    контроля ИИ. Это же место даёт рекомендации по установке камер, которые ТЗ
    требует в презентации: система сама показывает, где не хватает обзора.
    """
    if not django_bridge.ensure_django_ready():
        return []
    try:
        from core.models import Zone

        zones = Zone.objects.all()
        zones = zones.filter(site=site) if site is not None else zones.filter(site__is_legacy=True)

        uncovered = []
        for zone in zones.prefetch_related("cameras__frame_zones"):
            has_work_zone = any(
                frame_zone.kind == "work"
                for camera in zone.cameras.all()
                for frame_zone in camera.frame_zones.all()
            )
            if not has_work_zone:
                uncovered.append(zone.name)
        return uncovered
    except Exception:
        logger.exception("Не удалось определить непокрытые зоны")
        return []
