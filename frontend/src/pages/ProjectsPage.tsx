import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { cameraReferenceImageUrl, fetchProjects, type ProjectSummary } from "../api";
import { ProjectMiniMap } from "../components/ProjectMiniMap";
import "./ProjectsPage.css";

/**
 * Фотография последнего кадра камеры проекта вместо сухой мини-карты — живая картинка
 * с площадки выглядит премиальнее, чем отвлечённая точка на карте. Падает обратно на мини-карту,
 * если у проекта ещё нет ни одного снимка (нет `photo_camera_id`) или файл не загрузился.
 */
function ProjectCardMedia({ project }: { project: ProjectSummary }) {
  const [photoFailed, setPhotoFailed] = useState(false);

  if (project.photo_camera_id && !photoFailed) {
    return (
      <img
        className="sk-project-card__photo"
        src={cameraReferenceImageUrl(project.project_id, project.photo_camera_id)}
        crossOrigin="use-credentials"
        alt=""
        loading="lazy"
        onError={() => setPhotoFailed(true)}
      />
    );
  }
  return <ProjectMiniMap latitude={project.latitude} longitude={project.longitude} />;
}

export function ProjectsPage() {
  const { user } = useAuth();
  const location = useLocation();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  // Сообщение от ProjectContext при недоступном/удалённом проекте (см. план,
  // «Внутри проекта»: обратно к списку с объяснением, а не переключение на другой проект).
  const redirectMessage = (location.state as { message?: string } | null)?.message ?? null;

  useEffect(() => {
    let cancelled = false;
    fetchProjects()
      .then((data) => {
        if (!cancelled) setProjects(data.projects);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    if (!projects) return [];
    const q = query.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (p) => p.name.toLowerCase().includes(q) || p.address.toLowerCase().includes(q),
    );
  }, [projects, query]);

  return (
    <div className="sk-projects-page">
      <header className="sk-projects-page__header">
        <div>
          <h1>Проекты</h1>
          <p className="sk-table__muted">
            {user?.role === "admin"
              ? "Все проекты компании. Выберите проект, чтобы открыть его разделы."
              : "Проекты, к которым у вас есть доступ. Выберите проект, чтобы продолжить."}
          </p>
        </div>
        {user?.role === "admin" && (
          <Link to="/projects/new" className="sk-button">
            + Создать проект
          </Link>
        )}
      </header>

      {redirectMessage && <p className="sk-panel sk-panel--error sk-projects-page__notice">{redirectMessage}</p>}
      {error && (
        <p className="sk-panel sk-panel--error sk-projects-page__notice">
          Не удалось загрузить проекты: {error}
        </p>
      )}

      {projects && projects.length > 0 && (
        <div className="sk-projects-page__toolbar">
          <label className="sk-projects-search" htmlFor="project-search">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="7" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <input
              id="project-search"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск по названию или адресу"
            />
            {query && (
              <button
                type="button"
                className="sk-projects-search__clear"
                onClick={() => setQuery("")}
                aria-label="Очистить поиск"
              >
                ×
              </button>
            )}
          </label>
          <span className="sk-projects-page__count">
            {filtered.length} из {projects.length}
          </span>
        </div>
      )}

      {!projects && !error && (
        <div className="sk-projects-grid" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="sk-panel sk-project-card sk-project-card--skeleton">
              <div className="sk-project-card__skeleton-media" />
              <div className="sk-project-card__body">
                <div className="sk-project-card__skeleton-line" style={{ width: "70%" }} />
                <div className="sk-project-card__skeleton-line" style={{ width: "45%" }} />
                <div className="sk-project-card__skeleton-line" style={{ width: "55%" }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {projects && projects.length === 0 && (
        <div className="sk-panel sk-projects-page__empty">
          <p className="sk-empty-state">
            {user?.role === "admin"
              ? "Проектов пока нет. Создайте первый проект, чтобы начать работу."
              : "Вам пока не назначен ни один проект. Обратитесь к администратору."}
          </p>
        </div>
      )}

      {projects && projects.length > 0 && filtered.length === 0 && (
        <div className="sk-panel sk-projects-page__empty">
          <p className="sk-empty-state">По запросу «{query}» ничего не найдено.</p>
        </div>
      )}

      <div className="sk-projects-grid">
        {filtered.map((project) => (
          <Link
            key={project.project_id}
            to={`/projects/${project.project_id}`}
            className={`sk-panel sk-project-card sk-project-card--${project.status}`}
          >
            <div className="sk-project-card__media">
              <ProjectCardMedia project={project} />
              <div className="sk-project-card__scrim" aria-hidden="true" />
              <span className={`sk-project-status sk-project-status--${project.status}`}>
                {project.status_label_ru}
              </span>
            </div>
            <div className="sk-project-card__body">
              <h2>{project.name}</h2>
              <p className="sk-project-card__address">{project.address || "Адрес не указан"}</p>

              {project.current_stage_work_name ? (
                <div className="sk-project-card__stage">
                  <div className="sk-project-card__stage-top">
                    <span className="sk-project-card__stage-name" title={project.current_stage_work_name}>
                      {project.current_stage_work_name}
                    </span>
                    {project.current_stage_progress_percent !== null && (
                      <span className="sk-project-card__stage-percent">
                        {Math.round(project.current_stage_progress_percent)}%
                      </span>
                    )}
                  </div>
                  {project.current_stage_progress_percent !== null && (
                    <div className="sk-progress-bar sk-project-card__progress">
                      <div
                        className="sk-progress-bar__fill"
                        style={{ width: `${project.current_stage_progress_percent}%` }}
                      />
                    </div>
                  )}
                </div>
              ) : (
                <p className="sk-table__muted">Активный этап не задан</p>
              )}

              <div className="sk-project-card__stats">
                <span className="sk-project-card__stat" title="Снимков проанализировано">
                  📸 {project.total_observations}
                </span>
                {project.open_deviations_count > 0 && (
                  <span className="sk-project-card__stat sk-project-card__stat--danger" title="Открытые отклонения">
                    ⚠ {project.open_deviations_count}
                  </span>
                )}
              </div>

              <span className="sk-project-card__cta">
                Открыть проект
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
