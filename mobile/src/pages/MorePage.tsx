import { Link } from "react-router-dom";
import { useProject } from "../ProjectContext";
import "./MorePage.css";

const ITEMS = [
  {
    to: "map",
    label: "Карта площадки",
    hint: "Зоны, камеры, граница участка",
    icon: "M9 4 4 6v14l5-2 6 2 5-2V4l-5 2-6-2Z M9 4v14 M15 6v14",
  },
  {
    to: "forecast",
    label: "Прогноз",
    hint: "Срок сдачи, факторы риска",
    icon: "M4 16l5-6 4 3 7-9 M14 4h6v6",
  },
  {
    to: "analytics",
    label: "Аналитика",
    hint: "Графики, события, зоны",
    icon: "M4 20V10 M11 20V4 M18 20v-7",
  },
  {
    to: "analysis",
    label: "Снимок — AI-анализ",
    hint: "Загрузить и проверить фото",
    icon: "M4 8h3l1.5-2h7L17 8h3v11H4z M12 12.5a3 3 0 1 0 0.001 0",
  },
  {
    to: "settings",
    label: "Настройки проекта",
    hint: "Чувствительность, удаление",
    icon: "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z M4 12h1.6M18.4 12H20M12 4v1.6M12 18.4V20M6.3 6.3l1.1 1.1M16.6 16.6l1.1 1.1M17.7 6.3l-1.1 1.1M7.4 16.6l-1.1 1.1",
  },
  {
    to: "profile",
    label: "Профиль",
    hint: "Аккаунт, пароль, выход",
    icon: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z M4 20c1.5-4 5-6 8-6s6.5 2 8 6",
  },
] as const;

export function MorePage() {
  const { projectId } = useProject();
  return (
    <div>
      <h1>Ещё</h1>
      <div className="sk-more-list">
        {ITEMS.map((item) => (
          <Link key={item.to} to={`/projects/${projectId}/${item.to}`} className="sk-panel sk-more-item">
            <svg
              className="sk-more-item__icon"
              viewBox="0 0 24 24"
              width="22"
              height="22"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d={item.icon} />
            </svg>
            <div className="sk-more-item__text">
              <div className="sk-more-item__label">{item.label}</div>
              <div className="sk-more-item__hint">{item.hint}</div>
            </div>
            <span className="sk-more-item__chevron" aria-hidden="true">
              ›
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
