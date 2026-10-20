import { useEffect, useState } from "react";
import "./HeaderClock.css";
import { formatProjectClock } from "./projectTime";

/**
 * Текущие дата и время в шапке — рядом с погодой. Секунды не показываем и не
 * храним: минутной точности достаточно, а более частое обновление DOM не даёт
 * заметной пользы.
 */
export function HeaderClock({timeZone="UTC"}:{timeZone?:string}) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const clock=formatProjectClock(now,timeZone);
  return (
    <div className="sk-header-clock" title={`${timeZone} · ${clock.zone}`}>
      <span className="sk-header-clock__date">{clock.date}</span>
      <span className="sk-header-clock__time">{clock.time}<small>{clock.zone}</small></span>
    </div>
  );
}
