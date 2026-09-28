import { useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { avatarUrl } from "../api";
import { HeaderClock } from "./HeaderClock";
import { HeaderWeather } from "./HeaderWeather";
import { ProjectAssistant } from "./ProjectAssistant";
import "./AppShell.css";

const PROJECT_NAV_ITEMS = [
  { to: "", label: "Главная", icon: "home" },
  { to: "cameras", label: "Камеры", icon: "camera" },
  { to: "schedule", label: "Календарный план", icon: "calendar" },
  { to: "forecast", label: "Прогноз", icon: "trend" },
  { to: "analytics", label: "Аналитика", icon: "chart" },
  { to: "notifications", label: "Отклонения", icon: "bell" },
  { to: "map", label: "Карта", icon: "map" },
  { to: "settings", label: "Настройки проекта", icon: "gear" },
] as const;

/** Разделы вне конкретного объекта. «Проекты» первым пунктом — выбор проекта это первое действие
 * после входа. */
const GLOBAL_NAV_ITEMS = [
  { to: "/projects", label: "Проекты", icon: "grid" },
  { to: "/supervision", label: "Участок надзора", icon: "home" },
  { to: "/supervision/queue", label: "Очередь разбора", icon: "bell" },
  { to: "/demo-analysis", label: "Разбор фотографии", icon: "scan" },
] as const;

const ICON_PATHS: Record<(typeof PROJECT_NAV_ITEMS)[number]["icon"] | "grid" | "scan", string> = {
  home: "M3 11.5 12 4l9 7.5M5 10v9h5v-6h4v6h5v-9",
  camera: "M4 8h3l1.5-2h7L17 8h3v11H4z M12 12.5a3 3 0 1 0 0.001 0",
  map: "M9 4 4 6v14l5-2 6 2 5-2V4l-5 2-6-2Z M9 4v14 M15 6v14",
  calendar: "M4 5h16v16H4z M4 9h16 M8 3v4 M16 3v4",
  trend: "M4 16l5-6 4 3 7-9 M14 4h6v6",
  chart: "M4 20V10 M11 20V4 M18 20v-7",
  bell: "M6 10a6 6 0 0 1 12 0c0 4 1.5 5.5 1.5 5.5H4.5S6 14 6 10Z M10 19a2 2 0 0 0 4 0",
  gear: "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z M4 12h1.6M18.4 12H20M12 4v1.6M12 18.4V20M6.3 6.3l1.1 1.1M16.6 16.6l1.1 1.1M17.7 6.3l-1.1 1.1M7.4 16.6l-1.1 1.1",
  grid: "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z",
  scan: "M4 8V5a1 1 0 0 1 1-1h3M20 8V5a1 1 0 0 0-1-1h-3M4 16v3a1 1 0 0 0 1 1h3M20 16v3a1 1 0 0 1-1 1h-3M7 9l5 3 5-3M7 9v6l5 3 5-3V9",
};

function NavIcon({ name }: { name: keyof typeof ICON_PATHS }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

interface AppShellProps {
  children: ReactNode;
  /**
   * Проект, внутри которого сейчас находится пользователь. Когда он не задан
   * (например, на экране выбора или создания проекта), сайдбар показывает
   * только глобальный раздел «Проекты» — разделы вроде камер или графика без
   * выбранного проекта не имеют смысла. Каркас (ширина сайдбара, топбар)
   * остаётся неизменным в обоих случаях, чтобы переход внутрь проекта не
   * выглядел резким появлением новой структуры.
   */
  project?: {
    id: string;
    name: string;
    address?: string;
    latitude?: number | null;
    longitude?: number | null;
  };
  notificationCount?: number;
}

export function AppShell({ children, project, notificationCount = 0 }: AppShellProps) {
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  // На узких экранах сайдбар убирается за экран и выезжает по кнопке-гамбургеру в шапке
  // (см. .sk-sidebar--open в AppShell.css) вместо постоянной узкой колонки, чтобы оставить место под контент.
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const userAvatarUrl = user ? avatarUrl(user) : null;
  const closeMobileNav = () => setMobileNavOpen(false);

  return (
    <div className="sk-shell">
      {mobileNavOpen && (
        <div className="sk-sidebar-backdrop" onClick={closeMobileNav} aria-hidden="true" />
      )}
      <aside className={`sk-sidebar${mobileNavOpen ? " sk-sidebar--open" : ""}`} aria-label="Основная навигация">
        <div className="sk-sidebar__brand">
          <img className="sk-sidebar__logo" src="/logo.png" alt="BuildVision" />
          <button
            type="button"
            className="sk-sidebar__close"
            onClick={closeMobileNav}
            aria-label="Закрыть меню"
          >
            ✕
          </button>
        </div>

        {project ? (
          <>
            <div className="sk-sidebar__project">
              <Link to="/projects" className="sk-sidebar__all-projects" onClick={closeMobileNav}>
                ← Все проекты
              </Link>
              <div className="sk-sidebar__project-name" title={project.name}>
                {project.name}
              </div>
            </div>

            <nav className="sk-sidebar__nav">
              {PROJECT_NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={`/projects/${project.id}${item.to ? `/${item.to}` : ""}`}
                  end={item.to === ""}
                  className={({ isActive }) => `sk-sidebar__link${isActive ? " sk-sidebar__link--active" : ""}`}
                  onClick={closeMobileNav}
                >
                  <NavIcon name={item.icon} />
                  <span>{item.label}</span>
                  {item.to === "notifications" && notificationCount > 0 && (
                    <span className="sk-sidebar__badge">{notificationCount}</span>
                  )}
                </NavLink>
              ))}
            </nav>
          </>
        ) : (
          <>
            <div className="sk-sidebar__project">
              <span className="sk-sidebar__scope-label">Рабочее пространство</span>
              <div className="sk-sidebar__project-name">{user?.role_label ?? "BuildVision"}</div>
            </div>

            <nav className="sk-sidebar__nav">
              {GLOBAL_NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end
                  className={({ isActive }) =>
                    `sk-sidebar__link${isActive ? " sk-sidebar__link--active" : ""}`
                  }
                  onClick={closeMobileNav}
                >
                  <NavIcon name={item.icon} />
                  <span>{item.label}</span>
                  {item.to === "/supervision/queue" && notificationCount > 0 && (
                    <span className="sk-sidebar__badge">{notificationCount}</span>
                  )}
                </NavLink>
              ))}
            </nav>

            <p className="sk-sidebar__hint">
              Разделы проекта — камеры, карта, график — откроются после выбора проекта.
            </p>
          </>
        )}

        <div className="sk-sidebar__footer">
          <img
            className="sk-sidebar__footer-logo"
            src="/partner-logo.png"
            alt="Градостроительный комплекс Москвы"
          />
        </div>
      </aside>

      <div className="sk-shell__main">
        <header className="sk-topbar">
          <button
            type="button"
            className="sk-topbar__burger"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Открыть меню"
          >
            <span />
            <span />
            <span />
          </button>
          {project && (
            <div className="sk-topbar__title">
              <span className="sk-topbar__title-name" title={project.name}>
                {project.name}
              </span>
              {project.address && (
                <span className="sk-topbar__title-address" title={project.address}>
                  {project.address}
                </span>
              )}
            </div>
          )}
          <div className="sk-topbar__spacer" />
          {project && <HeaderClock />}
          {project && (
            <HeaderWeather
              projectId={project.id}
              hasLocation={project.latitude != null && project.longitude != null}
            />
          )}
          {user && (
            <div className="sk-profile">
              <button
                type="button"
                className="sk-profile__trigger"
                onClick={() => setMenuOpen((v) => !v)}
                aria-expanded={menuOpen}
              >
                <span className="sk-profile__avatar" aria-hidden="true">
                  {userAvatarUrl ? (
                    <img className="sk-profile__avatar-img" src={userAvatarUrl} alt="" />
                  ) : (
                    user.full_name.slice(0, 1).toUpperCase()
                  )}
                </span>
                <span className="sk-profile__text">
                  <span className="sk-profile__name">{user.full_name}</span>
                  <span className="sk-profile__position">{user.display_position}</span>
                </span>
              </button>
              {menuOpen && (
                <div className="sk-profile__menu" role="menu">
                  <Link
                    to="/account"
                    className="sk-profile__menu-item"
                    onClick={() => setMenuOpen(false)}
                  >
                    Настройки профиля
                  </Link>
                  {user.role === "admin" && (
                    <Link
                      to="/system/learning"
                      className="sk-profile__menu-item"
                      onClick={() => setMenuOpen(false)}
                    >
                      Центр обучения AI
                    </Link>
                  )}
                  <button
                    type="button"
                    className="sk-profile__menu-item"
                    onClick={() => {
                      setMenuOpen(false);
                      void logout();
                    }}
                  >
                    Выйти
                  </button>
                </div>
              )}
            </div>
          )}
        </header>
        <main className="sk-shell__content">{children}</main>
      </div>

      {project && <ProjectAssistant projectId={project.id} projectName={project.name} />}
    </div>
  );
}
