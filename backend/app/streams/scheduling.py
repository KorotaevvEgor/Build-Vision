from dataclasses import dataclass
from datetime import datetime,date,time,timedelta,UTC
from zoneinfo import ZoneInfo

@dataclass(frozen=True)
class StreamSchedule:
    interval_minutes:int=15
    weekdays:tuple[int,...]=(0,1,2,3,4,5,6)
    start_local:time|None=None
    end_local:time|None=None
    timezone:str='Europe/Moscow'
    daily_limit:int=1440
    def __post_init__(self):
        ZoneInfo(self.timezone)
        if not 1<=self.interval_minutes<=1440 or not 1<=self.daily_limit<=1440:raise ValueError('Интервал и лимит: от 1 до 1440')
        if not self.weekdays or any(d not in range(7) for d in self.weekdays):raise ValueError('Выберите дни недели')
        if (self.start_local is None)!=(self.end_local is None) or (self.start_local is not None and self.start_local==self.end_local):raise ValueError('Проверьте время смены')

def window_anchor(s:StreamSchedule,at:datetime):
    local=at.astimezone(ZoneInfo(s.timezone));day=local.date();clock=local.time().replace(tzinfo=None)
    if s.start_local is not None:
        if s.start_local<s.end_local:
            if not s.start_local<=clock<s.end_local:return None
        else:
            if clock<s.end_local:day-=timedelta(days=1)
            elif clock<s.start_local:return None
    if day.weekday() not in s.weekdays:return None
    return datetime.combine(day,s.start_local or time(),ZoneInfo(s.timezone))

def in_window(s:StreamSchedule,at:datetime)->bool:return window_anchor(s,at) is not None

def is_slot(s:StreamSchedule,at:datetime)->bool:
    anchor=window_anchor(s,at)
    return anchor is not None and int((at.astimezone(UTC)-anchor.astimezone(UTC)).total_seconds()//60)%s.interval_minutes==0

def next_slot(s:StreamSchedule,after:datetime)->datetime:
    at=after.astimezone(UTC).replace(second=0,microsecond=0)+timedelta(minutes=1)
    for _ in range(9*1440):
        if is_slot(s,at):return at
        at+=timedelta(minutes=1)
    raise ValueError('Не найден следующий интервал')

def estimated_weekly_frames(s:StreamSchedule,week_start:date)->int:
    tz=ZoneInfo(s.timezone);at=datetime.combine(week_start,time(),tz).astimezone(UTC);end=datetime.combine(week_start+timedelta(days=7),time(),tz).astimezone(UTC);counts={}
    while at<end:
        if is_slot(s,at):
            day=at.astimezone(tz).date();counts[day]=min(s.daily_limit,counts.get(day,0)+1)
        at+=timedelta(minutes=1)
    return sum(counts.values())
