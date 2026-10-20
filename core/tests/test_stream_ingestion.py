import sys,types,uuid
from pathlib import Path
from datetime import datetime,UTC
from unittest.mock import patch
from django.test import TestCase
from core.models import ConstructionSite,Zone,Camera,Observation
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app.observation_ingestion import ingest_observation

class StreamIngestionTests(TestCase):
 def test_unknown_capture_time_remains_unconfirmed(self):
  from tempfile import TemporaryDirectory
  calls=[];identity=uuid.uuid4()
  with TemporaryDirectory(dir='D:/dev/caches' if sys.platform=='win32' else None) as d:
   p=Path(d)/'test.jpg';p.write_bytes(b'image')
   def pipeline(**kw):calls.append(kw);return {'observation_id':str(identity),'saved_to_db':True}
   with patch.dict(sys.modules,{'app.projects_router':types.SimpleNamespace(_run_observation_pipeline=pipeline)}):
    result=ingest_observation(site=None,zone_id='zone',camera_id='cam',image_path=p,capture_received_at=datetime.now(UTC),source_capture_id=identity)
  self.assertFalse(calls[0]['date_confirmed']);self.assertIsNone(calls[0]['captured_at']);self.assertIsNone(calls[0]['observed_date']);self.assertEqual(calls[0]['source_observation_id'],identity)
 def test_existing_observation_does_not_run_detector_twice(self):
  site=ConstructionSite.objects.create(name='Ingest');z=Zone.objects.create(site=site,name='Zone',external_id='ingest-zone',geometry_geojson={});c=Camera.objects.create(zone=z,name='Camera',external_id='ingest-cam',latitude=55,longitude=37)
  o=Observation.objects.create(camera=c,zone=z,image_path='image.jpg',image_sha256='a'*64,overall_status='no_deviation',overall_explanation='')
  with patch.dict(sys.modules,{'app.projects_router':types.SimpleNamespace(_run_observation_pipeline=lambda **_:self.fail('Duplicate analysis'))}):
   result=ingest_observation(site=site,zone_id=z.external_id,camera_id=c.external_id,image_path=Path('missing.jpg'),capture_received_at=datetime.now(UTC),source_capture_id=o.pk)
  self.assertEqual(result['observation_id'],str(o.pk))
