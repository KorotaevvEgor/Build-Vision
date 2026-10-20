from types import SimpleNamespace
from unittest.mock import patch
import sys
from pathlib import Path
from django.test import SimpleTestCase
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"backend"))
from app import projects_router as r

class ScheduleFastLoadTests(SimpleTestCase):
    def test_calendar_skips_factors_but_preserves_network(self):
        report=SimpleNamespace(shift_days=18)
        graph={"stages":[{"stage_id":"s1","is_critical":True}],"shift_days":18}
        ctx=SimpleNamespace(schedule=SimpleNamespace(is_demo=False))
        site=SimpleNamespace(status="active")
        with patch.object(r,"get_context",return_value=ctx),patch.object(r.insights,"reference_date"),patch.object(r.schedule_network,"build_report",return_value=report),patch.object(r.schedule_network,"to_dict",side_effect=lambda report:dict(graph)),patch.object(r,"_compute_delay_breakdown",return_value={"available":True}) as factors:
            fast=r.get_project_schedule_network(include_breakdown=False,site=site)
            factors.assert_not_called()
            self.assertEqual(fast["stages"],graph["stages"])
            self.assertEqual(fast["shift_days"],18)
            full=r.get_project_schedule_network(site=site)
            factors.assert_called_once_with(report,ctx,site)
            self.assertEqual(full["delay_breakdown"],{"available":True})
