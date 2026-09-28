import { useCallback, useEffect, useState } from "react";
import {
  changeDeviationStatus,
  fetchDeviations,
  fetchProjectEvents,
  getObservationImageUrl,
  type DeviationLifecycleStatus,
  type DeviationRecord,
  type DeviationsResponse,
  type ProjectEventItem,
} from "../api";
import { useProject } from "../ProjectContext";
import "./NotificationsPage.css";

const NEXT_STATUSES: Record<DeviationLifecycleStatus, DeviationLifecycleStatus[]> = {
  detected: ["assigned", "resolved", "dismissed"],
  assigned: ["resolved", "dismissed"],
  resolved: ["confirmed", "detected"],
  confirmed: [],
  dismissed: ["detected"],
};

const STATUS_ACTION_LABELS: Record<DeviationLifecycleStatus, string> = {
  detected: "Вернуть в работу",
  assigned: "Взять в работу",
  resolved: "Отметить устранённым",
  confirmed: "Подтвердить устранение",
  dismissed: "Ложное срабатывание",
};

function formatMoment(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU");
}

export function NotificationsPage() {
  const { projectId } = useProject();
  const [data, setData] = useState<DeviationsResponse | null>(null);
  const [events, setEvents] = useState<ProjectEventItem[]>([]);
  const [filter, setFilter] = useState<DeviationLifecycleStatus | "">("");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showEvents, setShowEvents] = useState(false);

  const reload = useCallback(
    (status: DeviationLifecycleStatus | "") => {
      setError(null);
      fetchDeviations(projectId, status || undefined)
        .then(setData)
        .catch((err: Error) => setError(err.message));
      fetchProjectEvents(projectId, 15)
        .then((response) => setEvents(response.items))
        .catch(() => setEvents([]));
    },
    [projectId],
  );

  useEffect(() => {
    setData(null);
    setEvents([]);
    setExpandedId(null);
    reload(filter);
  }, [projectId, filter, reload]);

  const applyStatus = async (item: DeviationRecord, status: DeviationLifecycleStatus) => {
    setBusyId(item.id);
    setError(null);
    try {
      await changeDeviationStatus(projectId, item.id, { status });
      reload(filter);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить состояние");
    } finally {
      setBusyId(null);
    }
  };

  if (error && !data) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить отклонения: {error}</div>;
  }
  if (!data) {
    return <div className="sk-panel">Загрузка отклонений…</div>;
  }

  const openCount = (data.counts.detected ?? 0) + (data.counts.assigned ?? 0);

  return (
    <div>
      <h1>Отклонения</h1>

      {!data.available && <div className="sk-panel sk-panel--error">База данных недоступна.</div>}
      {error && <div className="sk-panel sk-panel--error">{error}</div>}

      <div className="sk-deviation-filters">
        <button type="button" className={`sk-chip${filter === "" ? " sk-chip--active" : ""}`} onClick={() => setFilter("")}>
          Все ({Object.values(data.counts).reduce((a, b) => a + b, 0)})
        </button>
        {data.statuses.map((status) => (
          <button key={status.key} type="button" className={`sk-chip${filter === status.key ? " sk-chip--active" : ""}`} onClick={() => setFilter(status.key)}>
            {status.label_ru} ({data.counts[status.key] ?? 0})
          </button>
        ))}
      </div>
      {openCount > 0 && <p className="sk-table__muted">В работе: {openCount}</p>}

      {data.items.length === 0 && (
        <div className="sk-panel">
          <p className="sk-empty-state">{filter ? "В этом состоянии отклонений нет." : "Отклонений не зафиксировано."}</p>
        </div>
      )}

      {data.items.map((item) => {
        const expanded = expandedId === item.id;
        return (
          <article key={item.id} className={`sk-panel sk-deviation sk-deviation--${item.severity}`}>
            <header className="sk-deviation__head">
              <div>
                <h2>{item.title}</h2>
                <p className="sk-deviation__meta">
                  {item.zone_name} · {item.kind_label_ru} · {formatMoment(item.detected_at)}
                  {item.occurrence_count > 1 && <> · снимков: {item.occurrence_count}</>}
                </p>
              </div>
              <span className={`sk-deviation__status sk-deviation__status--${item.status}`}>{item.status_label_ru}</span>
            </header>

            {item.is_on_critical_path && <p className="sk-deviation__critical">Этап на критическом пути — влияет на срок сдачи.</p>}

            <p className="sk-deviation__message">{item.message}</p>
            {item.resolution_note && <p className="sk-deviation__note">{item.resolution_note}</p>}
            {item.assignee && <p className="sk-deviation__meta">Ответственный: {item.assignee}</p>}

            {(item.before_observation_id || item.after_observation_id) && (
              <button type="button" className="sk-deviation__toggle" onClick={() => setExpandedId(expanded ? null : item.id)}>
                {expanded ? "Скрыть снимки" : "Показать снимки «до» и «после»"}
              </button>
            )}

            {expanded && (
              <div className="sk-deviation__photos">
                <figure>
                  <figcaption>До — выявлено</figcaption>
                  {item.before_observation_id ? (
                    <img src={getObservationImageUrl(projectId, item.before_observation_id)} crossOrigin="use-credentials" alt="Снимок «до»" />
                  ) : (
                    <p className="sk-empty-state">Снимок недоступен.</p>
                  )}
                </figure>
                <figure>
                  <figcaption>После — {item.auto_resolved ? "не воспроизвелось" : "закрыто вручную"}</figcaption>
                  {item.after_observation_id ? (
                    <img src={getObservationImageUrl(projectId, item.after_observation_id)} crossOrigin="use-credentials" alt="Снимок «после»" />
                  ) : (
                    <p className="sk-empty-state">Ещё не устранено.</p>
                  )}
                </figure>
              </div>
            )}

            {NEXT_STATUSES[item.status].length > 0 && (
              <div className="sk-deviation__actions">
                {NEXT_STATUSES[item.status].map((status) => (
                  <button
                    key={status}
                    type="button"
                    className={status === "confirmed" ? "sk-button" : "sk-button sk-button--secondary"}
                    disabled={busyId === item.id}
                    onClick={() => void applyStatus(item, status)}
                  >
                    {STATUS_ACTION_LABELS[status]}
                  </button>
                ))}
              </div>
            )}
          </article>
        );
      })}

      <div className="sk-panel">
        <button type="button" className="sk-deviation__toggle" onClick={() => setShowEvents((v) => !v)}>
          {showEvents ? "Скрыть ленту событий" : "Показать ленту событий"}
        </button>
        {showEvents && (
          <ul className="sk-event-feed__list">
            {events.length === 0 && <p className="sk-empty-state">Событий пока нет.</p>}
            {events.map((event) => (
              <li key={event.id} className="sk-event">
                <div className="sk-event__head">
                  <span className="sk-event__kind">{event.kind_label_ru}</span>
                  <time>{formatMoment(event.created_at)}</time>
                </div>
                <div className="sk-event__title">{event.title}</div>
                {(event.old_value || event.new_value) && (
                  <div className="sk-event__transition">
                    {event.old_value || "—"} → {event.new_value || "—"}
                  </div>
                )}
                <div className="sk-event__actor">
                  {event.actor ? event.actor : "система"}
                  {event.zone_name ? ` · ${event.zone_name}` : ""}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
