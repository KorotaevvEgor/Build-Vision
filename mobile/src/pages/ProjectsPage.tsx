import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { fetchProjects, type ProjectSummary } from "../api";
import "./ProjectsPage.css";

export function ProjectsPage() {
  const { user } = useAuth();
  const location = useLocation();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
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
    <div>
      <h1>Проекты</h1>

      {redirectMessage && <p className="sk-panel sk-panel--error">{redirectMessage}</p>}
      {error && <p className="sk-panel sk-panel--error">Не удалось загрузить проекты: {error}</p>}
      {!projects && !error && <div className="sk-panel">Загрузка проектов…</div>}

      {projects && projects.length > 0 && (
        <div className="sk-field">
          <label htmlFor="project-search">Поиск</label>
          <input
            id="project-search"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Название или адрес"
          />
        </div>
      )}

      {user?.role === "admin" && (
        <Link to="/projects/new" className="sk-button sk-button--block" style={{ marginBottom: "var(--sk-space-4)" }}>
          + Создать проект
        </Link>
      )}

      {projects && projects.length === 0 && (
        <div className="sk-panel">
          <p className="sk-empty-state">
            {user?.role === "admin"
              ? "Проектов пока нет. Создайте первый проект."
              : "Вам пока не назначен ни один проект."}
          </p>
        </div>
      )}

      {projects && projects.length > 0 && filtered.length === 0 && (
        <div className="sk-panel">
          <p className="sk-empty-state">По запросу «{query}» ничего не найдено.</p>
        </div>
      )}

      <div className="sk-project-list">
        {filtered.map((project) => (
          <Link key={project.project_id} to={`/projects/${project.project_id}`} className="sk-panel sk-project-item">
            <div className="sk-project-item__header">
              <h2>{project.name}</h2>
              <span className={`sk-project-status sk-project-status--${project.status}`}>
                {project.status_label_ru}
              </span>
            </div>
            <p className="sk-table__muted">{project.address || "Адрес не указан"}</p>
            <p className="sk-table__muted">
              {project.current_stage_work_name
                ? `Текущий этап: ${project.current_stage_work_name}`
                : "Активный этап не задан"}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
