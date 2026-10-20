import sys
from pathlib import Path
from django.core.management.base import BaseCommand
class Command(BaseCommand):
 help='Получает кадры видеопотоков по расписанию'
 def handle(self,*args,**options):
  sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'backend'))
  from app.streams.worker import StreamWorker
  StreamWorker().run()
