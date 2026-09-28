import { useEffect, useState } from "react";
import "./HeaderClock.css";

function formatDate(date: Date): string {
  const label = date.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

/**
 * Текущие дата и время в шапке — рядом с погодой. Секунды не показываем и не
 * храним: минутной точности достаточно, а более частое обновление DOM не даёт
 * заметной пользы.
 */
export function HeaderClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="sk-header-clock" title={now.toLocaleString("ru-RU")}>
      <span className="sk-header-clock__date">{formatDate(now)}</span>
      <span className="sk-header-clock__time">{formatTime(now)}</span>
    </div>
  );
}
