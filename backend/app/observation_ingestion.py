"""Shared ingestion entry for captured frames; no HTTP session is fabricated."""
from datetime import datetime
from pathlib import Path
from uuid import UUID
from starlette.datastructures import UploadFile

def ingest_observation(*,site,zone_id:str,camera_id:str,image_path:Path,capture_received_at:datetime,source_capture_id)->dict:
    from core.models import Observation
    from .projects_router import _run_observation_pipeline
    identity=UUID(str(source_capture_id))
    existing=Observation.objects.filter(pk=identity,camera__external_id=camera_id,zone__site=site).first()
    if existing:return {'observation_id':str(existing.pk),'saved_to_db':True}
    with image_path.open('rb') as stream:
        result=_run_observation_pipeline(site=site,zone_id=zone_id,observed_date=None,date_confirmed=False,camera_id=camera_id,image=UploadFile(stream,filename='stream.jpg'),require_zone_in_schedule=False,captured_at=None,source_observation_id=identity)
    if not result.get('saved_to_db'):raise ValueError('Наблюдение не сохранено')
    return result
