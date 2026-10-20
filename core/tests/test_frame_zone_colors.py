import sys
from pathlib import Path
from django.test import TestCase
from pydantic import ValidationError
from core.models import Camera, ConstructionSite, Zone, FrameZone
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"backend"))
from app.projects_router import FrameZonePayload, _replace_frame_zones, _frame_zone_to_dict

class FrameZoneColorTests(TestCase):
    def setUp(self):
        site=ConstructionSite.objects.create(name="Color test")
        zone=Zone.objects.create(site=site,external_id="color-zone",name="Zone",geometry_geojson={"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,0]]]})
        self.camera=Camera.objects.create(zone=zone,external_id="color-camera",name="Camera",latitude=0,longitude=0)
    def payload(self,**kw):
        return FrameZonePayload(name="Zone",kind="work",polygon=[[0,0],[100,0],[100,100]],**kw)
    def test_custom_color_survives_save_and_read(self):
        _replace_frame_zones(self.camera,[self.payload(color="#AB12EF")],1920,1080)
        self.assertEqual(_frame_zone_to_dict(FrameZone.objects.get(camera=self.camera))["color"],"#ab12ef")
    def test_legacy_payload_uses_default(self):
        _replace_frame_zones(self.camera,[self.payload()],1920,1080)
        self.assertEqual(FrameZone.objects.get(camera=self.camera).color,"")
    def test_invalid_colors_rejected(self):
        for color in ["red","#fff","#1234567","url(example)"]:
            with self.subTest(color=color),self.assertRaises(ValidationError):self.payload(color=color)
