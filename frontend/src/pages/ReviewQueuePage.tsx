import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  changeDeviationStatus,
  fetchReviewQueue,
  getObservationImageUrl,
  type ReviewQueueItem,
} from "../api";
import "./ReviewQueuePage.css";

type Decision = "confirmed" | "dismissed" | "assigned";

const DECISIONS: { key: Decision; label: string; hint: string; primary?: boolean }[] = [
  {
    key: "confirmed",
    label: "Подтвердить нарушение",
    hint: "Отклонение реально, требует устранения",
    primary: true,
  },
  {
    key: "assigned",
    label: "Нужен выезд",
    hint: "По снимку не разобрать, беру на себя проверку на месте",
  },
  {
    key: "dismissed",
    label: "Ложное срабатывание",
    hint: "Система ошиблась, нарушения нет",
  },
];

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("ru-RU") : "дата не подтверждена";
}

export function ReviewQueuePage() {
  const [items, setItems] = useState<ReviewQueueItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [index, setIndex] = useState(0);
  const [handled, setHandled] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    fetchReviewQueue(60)
      .then((response) => {
        setItems(response.items);
        setTotal(response.total);
        setIndex(0);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  const current = items?.[index] ?? null;

  const decide = async (decision: Decision) => {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await changeDeviationStatus(current.project_id, current.id, { status: decision });
      setHandled((value) => value + 1);
      // Карточка убирается из локального списка, а не перезагружается целиком:
      // иначе после каждого решения очередь пересобиралась бы и прыгала под рукой.
      setItems((list) => (list ? list.filter((_, position) => position !== index) : list));
      setTotal((value) => Math.max(0, value - 1));
      setIndex((value) => Math.min(value, Math.max(0, (items?.length ?? 1) - 2)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось применить решение");
    } finally {
      setBusy(false);
    }
  };

  if (error && !items) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить очередь: {error}</div>;
  }
  if (!items) {
    return <div className="sk-panel">Собираем очередь…</div>;
  }

  return (
    <div className="sk-queue">
      <header className="sk-queue__head">
        <div>
          <Link to="/supervision" className="sk-queue__back">
            ← Участок надзора
          </Link>
          <h1>Очередь разбора</h1>
          <p className="sk-table__muted">
            Карточки отсортированы по важности: сначала то, что двигает дату сдачи, затем по
            критичности, затем повторяющееся. Решение по каждой занимает несколько секунд.
          </p>
        </div>
        <div className="sk-queue__counter">
          <strong>{items.length}</strong>
          <span>осталось</span>
          {handled > 0 && <span className="sk-queue__handled">разобрано за сеанс: {handled}</span>}
        </div>
      </header>

      {error && <div className="sk-panel sk-panel--error">{error}</div>}

      {items.length === 0 ? (
        <div className="sk-panel sk-queue__empty">
          <h2>Очередь пуста</h2>
          <p>
            {handled > 0
              ? `Вы разобрали ${handled} — на участке не осталось отклонений, ждущих решения.`
              : "Отклонений, требующих решения, нет."}
          </p>
          <Link to="/supervision" className="sk-button">
            Вернуться на участок
          </Link>
        </div>
      ) : (
        current && (
          <article className={`sk-panel sk-queue-card sk-queue-card--${current.severity}`}>
            <header className="sk-queue-card__head">
              <div>
                <h2>{current.title}</h2>
                <p className="sk-queue-card__meta">
                  {current.project_name} · {current.kind_label_ru} · снимок от{" "}
                  {formatDate(current.observed_date)}
                  {current.occurrence_count > 1 && (
                    <> · подтверждено снимками: {current.occurrence_count}</>
                  )}
                </p>
              </div>
              <span className={`sk-queue-card__severity sk-queue-card__severity--${current.severity}`}>
                {current.severity_label_ru}
              </span>
            </header>

            {current.is_on_critical_path && (
              <p className="sk-queue-card__critical">
                Работа на критическом пути: запаса времени нет, задержка сдвигает дату сдачи
                объекта.
              </p>
            )}

            <div className="sk-queue-card__body">
              <div className="sk-queue-card__photo">
                {current.observation_id ? (
                  <img
                    src={getObservationImageUrl(current.project_id, current.observation_id)}
                    crossOrigin="use-credentials"
                    alt="Снимок, на котором выявлено отклонение"
                  />
                ) : (
                  <p className="sk-empty-state">Снимок недоступен.</p>
                )}
              </div>
              <div className="sk-queue-card__text">
                <p>{current.message}</p>
                {current.work_name && (
                  <p className="sk-table__muted">Работа графика: {current.work_name}</p>
                )}
                {current.equipment.length > 0 && (
                  <p className="sk-table__muted">Техника: {current.equipment.join(", ")}</p>
                )}
                <Link to={`/projects/${current.project_id}`} className="sk-queue-card__link">
                  Открыть объект целиком
                </Link>
              </div>
            </div>

            <div className="sk-queue-card__actions">
              {DECISIONS.map((decision) => (
                <button
                  key={decision.key}
                  type="button"
                  className={decision.primary ? "sk-button" : "sk-button sk-button--secondary"}
                  disabled={busy}
                  title={decision.hint}
                  onClick={() => void decide(decision.key)}
                >
                  {decision.label}
                </button>
              ))}
              <button
                type="button"
                className="sk-queue-card__skip"
                disabled={busy || index >= items.length - 1}
                onClick={() => setIndex((value) => value + 1)}
              >
                Отложить
              </button>
            </div>
          </article>
        )
      )}

      {total > items.length && (
        <p className="sk-table__muted">
          Показаны первые {items.length} из {total}. Остальные подтянутся после обновления.
        </p>
      )}
    </div>
  );
}
