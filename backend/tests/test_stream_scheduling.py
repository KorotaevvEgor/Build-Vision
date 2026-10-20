from datetime import datetime,time,UTC,date
import pytest
from app.streams.scheduling import StreamSchedule,in_window,next_slot,estimated_weekly_frames

def test_default_daily_count():
 s=StreamSchedule()
 assert estimated_weekly_frames(s,date(2026,10,19))==672
 assert next_slot(s,datetime(2026,10,20,0,0,tzinfo=UTC))==datetime(2026,10,20,0,15,tzinfo=UTC)

def test_night_shift_and_local_day():
 s=StreamSchedule(weekdays=(0,),start_local=time(22),end_local=time(6),timezone='Europe/Moscow')
 assert in_window(s,datetime(2026,10,19,23,tzinfo=UTC))
 assert not in_window(s,datetime(2026,10,20,23,tzinfo=UTC))

def test_invalid_intervals_and_window():
 for n in [0,1441]:
  with pytest.raises(ValueError):StreamSchedule(interval_minutes=n)
 with pytest.raises(ValueError):StreamSchedule(start_local=time(6),end_local=time(6))

def test_dst_and_short_window():
 s=StreamSchedule(interval_minutes=60,start_local=time(9),end_local=time(9,30),timezone='Europe/Berlin')
 assert estimated_weekly_frames(s,date(2026,10,19))==7
 assert next_slot(s,datetime(2026,10,25,7,tzinfo=UTC))==datetime(2026,10,25,8,tzinfo=UTC)
