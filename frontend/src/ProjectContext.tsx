import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, useParams } from "react-router-dom";
import { ApiError, fetchProjectDetail, type ProjectDetail } from "./api";

interface ProjectContextValue {
  projectId: string;
  project: ProjectDetail;
  /** Перезагрузить сведения о проекте (например, после смены статуса из другого места). */
  reload: () => void;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

/**
 * Оборачивает вложенные маршруты `/projects/:projectId/...`.
 *
 * Резолвит доступ к проекту на сервере при каждом входе в раздел: недоступный
 * (чужой/удалённый) проект возвращает пользователя к списку с объяснением,
 * а не переключает на другую площадку (см. план, «Внутри проекта»).
 */
export function ProjectProvider({ children }: { children: ReactNode }) {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!projectId) return;
    // Очищаем предыдущий проект немедленно, чтобы дочерние страницы не успели
    // отрисовать данные другого проекта, пока грузится новый (см. план,
    // «Состояние клиентов и карты»).
    let cancelled = false;
    setProject(null);
    setNotFound(false);
    setError(null);
    fetchProjectDetail(projectId)
      .then((data) => {
        if (cancelled) return;
        setProject(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError(err instanceof Error ? err.message : "Не удалось загрузить проект");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, reloadToken]);

  if (!projectId) {
    return <Navigate to="/projects" replace />;
  }
  if (notFound) {
    return (
      <Navigate
        to="/projects"
        replace
        state={{ message: "Проект недоступен: он удалён или доступ к нему отозван." }}
      />
    );
  }
  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить проект: {error}</div>;
  }
  if (!project) {
    return <div className="sk-panel">Загрузка проекта…</div>;
  }

  return (
    <ProjectContext.Provider
      value={{ projectId, project, reload: () => setReloadToken((t) => t + 1) }}
    >
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject должен использоваться внутри ProjectProvider");
  return ctx;
}
