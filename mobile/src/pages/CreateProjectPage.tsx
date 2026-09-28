import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import {
  createProject,
  fetchAssignableUsers,
  fetchProjectStatuses,
  type AssignableUser,
  type ProjectStatus,
} from "../api";

export function CreateProjectPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [statuses, setStatuses] = useState<{ key: ProjectStatus; label_ru: string }[]>([]);
  const [users, setUsers] = useState<AssignableUser[]>([]);
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("preparation");
  const [memberIds, setMemberIds] = useState<Set<number>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user?.role !== "admin") return;
    fetchProjectStatuses()
      .then((data) => setStatuses(data.statuses))
      .catch(() => setStatuses([]));
    fetchAssignableUsers()
      .then((data) => setUsers(data.users))
      .catch(() => setUsers([]));
  }, [user]);

  if (user && user.role !== "admin") {
    return <Navigate to="/projects" replace />;
  }

  const toggleMember = (id: number) => {
    setMemberIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Укажите название проекта");
      return;
    }

    setSubmitting(true);
    try {
      const { project } = await createProject({
        name: trimmedName,
        address: address.trim(),
        status,
        latitude: null,
        longitude: null,
        memberUserIds: Array.from(memberIds),
      });
      navigate(`/projects/${project.project_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать проект");
      setSubmitting(false);
    }
  };

  return (
    <div>
      <h1>Новый проект</h1>
      <form className="sk-panel" onSubmit={onSubmit}>
        <div className="sk-field">
          <label htmlFor="name">Название</label>
          <input id="name" value={name} onChange={(e) => setName(e.target.value)} disabled={submitting} />
        </div>
        <div className="sk-field">
          <label htmlFor="address">Адрес</label>
          <input id="address" value={address} onChange={(e) => setAddress(e.target.value)} disabled={submitting} />
        </div>
        <div className="sk-field">
          <label htmlFor="status">Статус</label>
          <select
            id="status"
            value={status}
            onChange={(e) => setStatus(e.target.value as ProjectStatus)}
            disabled={submitting}
          >
            {statuses.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label_ru}
              </option>
            ))}
          </select>
        </div>
        <p className="sk-table__muted">
          Координаты и границу можно задать позже через Django admin.
        </p>
        <div className="sk-field">
          <label>Участники</label>
          {users.length === 0 ? (
            <p className="sk-empty-state">Нет пользователей для назначения.</p>
          ) : (
            users.map((u) => (
              <label key={u.id} className="sk-checkbox">
                <input
                  type="checkbox"
                  checked={memberIds.has(u.id)}
                  onChange={() => toggleMember(u.id)}
                  disabled={submitting}
                />
                {u.full_name} ({u.username})
              </label>
            ))
          )}
        </div>
        {error && <p className="sk-panel sk-panel--error">{error}</p>}
        <button type="submit" className="sk-button sk-button--block" disabled={submitting}>
          {submitting ? "Создаём…" : "Создать проект"}
        </button>
      </form>
    </div>
  );
}
