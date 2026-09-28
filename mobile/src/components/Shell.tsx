import { Link, Outlet } from "react-router-dom";
import { useProject } from "../ProjectContext";
import { BottomNav } from "./BottomNav";
import "./Shell.css";

export function Shell() {
  const { project } = useProject();
  return (
    <div className="sk-shell">
      <header className="sk-shell__header">
        <Link to="/projects" className="sk-shell__all-projects">
          ← Все проекты
        </Link>
        <div className="sk-shell__project-name">{project.name}</div>
      </header>
      <main className="sk-shell__content">
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}
