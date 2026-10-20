import signal,threading,time
from datetime import datetime,UTC
from django.db import close_old_connections
from core.models import StreamWorkerHeartbeat
from .service import schedule_due,claim_due_jobs,run_capture_job,process_analysis_job,clean_test_frames

class StreamWorker:
 def __init__(self):self.stop=threading.Event();self.capture_thread=None;self.analysis_thread=None
 def _capture(self,j):
  close_old_connections()
  try:run_capture_job(j)
  finally:close_old_connections()
 def _analysis(self):
  close_old_connections()
  try:process_analysis_job()
  finally:close_old_connections()
 def run(self):
  import logging
  log=logging.getLogger(__name__)
  for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:self.stop.set())
  while not self.stop.is_set():
   try:
    close_old_connections();now=datetime.now(UTC);StreamWorkerHeartbeat.objects.update_or_create(key='capture',defaults={'updated_at':now})
    schedule_due(now);clean_test_frames(now)
    if not self.capture_thread or not self.capture_thread.is_alive():
     jobs=claim_due_jobs(now)
     if jobs:self.capture_thread=threading.Thread(target=self._capture,args=(jobs[0],),daemon=True);self.capture_thread.start()
    if not self.analysis_thread or not self.analysis_thread.is_alive():
     self.analysis_thread=threading.Thread(target=self._analysis,daemon=True);self.analysis_thread.start()
   except Exception:log.error('Stream worker iteration failed; retrying without exposing source details')
   self.stop.wait(5)
  if self.capture_thread:self.capture_thread.join(22)
  StreamWorkerHeartbeat.objects.filter(key='capture').delete()
