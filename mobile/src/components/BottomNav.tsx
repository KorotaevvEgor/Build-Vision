import { NavLink } from "react-router-dom";
import { useProject } from "../ProjectContext";
import "./BottomNav.css";

const ITEMS = [
  { to: "", label: "Главная", icon: "M3 11.5 12 4l9 7.5M5 10v9h5v-6h4v6h5v-9" },
  { to: "cameras", label: "Камеры", icon: "M4 8h3l1.5-2h7L17 8h3v11H4z M12 12.5a3 3 0 1 0 0.001 0" },
  { to: "schedule", label: "График", icon: "M4 5h16v16H4z M4 9h16 M8 3v4 M16 3v4" },
  { to: "notifications", label: "Отклонения", icon: "M6 10a6 6 0 0 1 12 0c0 4 1.5 5.5 1.5 5.5H4.5S6 14 6 10Z M10 19a2 2 0 0 0 4 0" },
  { to: "more", label: "Ещё", icon: "M5 12h.01M12 12h.01M19 12h.01" },
] as const;

export function BottomNav() {
  const { projectId } = useProject();
  return (
    <nav className="sk-bottom-nav" aria-label="Основная навигация">
      {ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={`/projects/${projectId}${item.to ? `/${item.to}` : ""}`}
          end={item.to === ""}
          className={({ isActive }) => `sk-bottom-nav__link${isActive ? " sk-bottom-nav__link--active" : ""}`}
        >
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d={item.icon} />
          </svg>
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
