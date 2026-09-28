"""Что получилось после импорта хроники: объекты, снимки, отклонения, графики.

Быстрая проверка состояния базы без захода в интерфейс.

Запуск:
    .venv\\Scripts\\python.exe scripts\\show_imported_history.py
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "backend"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin_panel.settings")
django.setup()

from app import schedule_network
from app.schedule import load_schedule

from core.models import (
    ConstructionSite,
    Detection,
    Deviation,
    Observation,
    ProjectEvent,
    Stage,
)


def main() -> int:
    sites = ConstructionSite.objects.exclude(external_key="").order_by("name")
    today = datetime.now(UTC).date()

    print(
        f"Объектов: {sites.count()}, наблюдений: {Observation.objects.count()}, "
        f"детекций: {Detection.objects.count()}, отклонений: {Deviation.objects.count()}, "
        f"событий: {ProjectEvent.objects.count()}\n"
    )

    for site in sites:
        observations = Observation.objects.filter(zone__site=site)
        dated = observations.filter(observed_date__isnull=False).order_by("observed_date")
        deviations = Deviation.objects.filter(zone__site=site)
        detections = Detection.objects.filter(observation__zone__site=site)
        last = dated.last()

        print(f"=== {site.name}")
        print(
            f"    снимков {observations.count()} (с датой {dated.count()}), "
            f"детекций {detections.count()}, отклонений {deviations.count()} "
            f"(открытых {deviations.filter(status__in=Deviation.OPEN_STATUSES).count()})"
        )
        if last:
            print(
                f"    период {dated.first().observed_date} .. {last.observed_date}, "
                f"последний снимок {(today - last.observed_date).days} дн. назад"
            )
        else:
            print("    дат на снимках нет — календарное сопоставление недоступно")

        stages = Stage.objects.filter(zone__site=site).order_by("start_date")
        for stage in stages:
            print(f"      план {stage.start_date} .. {stage.end_date}  {stage.work_name}")

        if stages:
            report = schedule_network.build_report(load_schedule(site=site), today, site=site)
            if report.available:
                print(
                    f"    срок сдачи: план {report.baseline_finish}, прогноз "
                    f"{report.projected_finish}, сдвиг {report.shift_days} дн. — "
                    f"{schedule_network.PROJECT_STATUS_LABELS[report.status]}"
                )
        print()

    print("Открытые отклонения:")
    for item in Deviation.objects.filter(status__in=Deviation.OPEN_STATUSES).order_by("-detected_at"):
        mark = " [критический путь]" if item.is_on_critical_path else ""
        print(f"  [{item.severity:8s}] {item.zone.site.name[:28]:28s} {item.title[:50]}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
