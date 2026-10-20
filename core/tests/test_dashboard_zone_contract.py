from types import SimpleNamespace
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from django.test import SimpleTestCase
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import projects_router as r

class DashboardZoneContractTests(SimpleTestCase):
    def test_http_dashboard_constructs_zone_references(self):
        api=FastAPI()
        site=object()
        api.include_router(r.router)
        api.dependency_overrides[r.get_project_site]=lambda: site
        ctx=SimpleNamespace(site_geojson={'features':[{'properties':{'kind':'zone','id':'work-zone','name':'Рабочая зона'}}]},schedule=object(),weather_rules=[],site_latitude=55.7,site_longitude=37.6)
        with patch.object(r,'get_context',return_value=ctx), patch.object(r.insights,'dashboard_summary',return_value={'available':True}) as summary, TestClient(api) as client:
            response=client.get('/api/projects/39/dashboard')
            self.assertEqual(response.status_code,200,response.text)
            zone=summary.call_args.kwargs['zones'][0]
            self.assertEqual((zone.zone_id,zone.name),('work-zone','Рабочая зона'))

