import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { fetchSupervision, type SupervisionObject, type SupervisionResponse } from "../api";
import "./SupervisionPage.css";

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("ru-RU") : "—";
}

function plural(days: number, forms: [string, string, string]): string {
  const n = Math.abs(days) % 100;
  const last = n % 10;
  if (n > 10 && n < 20) return forms[2];
  if (last === 1) return forms[0];
  if (last >= 2 && last <= 4) return forms[1];
  return forms[2];
}

/** Насколько давно был снимок — словами, а не сырым числом. */
function lastSeen(days: number | null): string {
  if (days === null) return "снимков с подтверждённой датой нет";
  if (days === 0) return "сегодня";
  if (days === 1) return "вчера";
  return `${days} ${plural(days, ["день", "дня", "дней"])} назад`;
}

export function SupervisionPage() {
  const { user } = useAuth();
  const [data, setData] = useState<SupervisionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSupervision()
      .then((response) => {
        if (!cancelled) setData(response);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить участок: {error}</div>;
  }
  if (!data) {
    return <div className="sk-panel">Собираем сводку по объектам…</div>;
  }

  const { totals } = data;

  const renderRow = (item: SupervisionObject) => (
    <Link
      key={item.project_id}
      to={`/projects/${item.project_id}`}
      className={`sk-object-row sk-object-row--${item.schedule_status}`}
    >
      <div className="sk-object-row__main">
        <div className="sk-object-row__name">
          {item.name}
          {item.on_critical_path_deviations > 0 && (
            <span className="sk-object-row__flag" title="Есть отклонения на критическом пути">
              ▲
            </span>
          )}
        </div>
        <div className="sk-object-row__stage">
          {item.current_work_name ?? item.stage_label ?? "Текущая работа не определена"}
        </div>
      </div>

      <div className="sk-object-row__metric">
        <span className="sk-object-row__label">Готовность</span>
        {item.readiness_percent !== null ? (
          <>
            <strong>{item.readiness_percent}%</strong>
            <span className="sk-object-row__sub">по снимку {formatDate(item.readiness_date)}</span>
          </>
        ) : (
          <strong className="sk-object-row__muted">—</strong>
        )}
      </div>

      <div className="sk-object-row__metric">
        <span className="sk-object-row__label">Срок сдачи</span>
        <strong>{item.schedule_status_label_ru}</strong>
        {item.shift_days !== 0 && (
          <span className="sk-object-row__sub">
            {item.shift_days > 0 ? "+" : "−"}
            {Math.abs(item.shift_days)} {plural(item.shift_days, ["день", "дня", "дней"])} к{" "}
            {formatDate(item.planned_finish_date)}
          </span>
        )}
      </div>

      <div className="sk-object-row__metric">
        <span className="sk-object-row__label">Отклонения</span>
        <strong className={item.critical_deviations > 0 ? "sk-object-row__danger" : ""}>
          {item.open_deviations}
        </strong>
        {item.resolved_awaiting_confirmation > 0 && (
          <span className="sk-object-row__sub">
            {item.resolved_awaiting_confirmation} ждёт подтверждения
          </span>
        )}
      </div>

      <div className="sk-object-row__metric">
        <span className="sk-object-row__label">Последний снимок</span>
        <strong className={item.is_stale ? "sk-object-row__danger" : ""}>
          {lastSeen(item.days_since_last_observation)}
        </strong>
        <span className="sk-object-row__sub">всего кадров: {item.observation_count}</span>
      </div>
    </Link>
  );

  return (
    <div className="sk-supervision">
      <header className="sk-supervision__head">
        <div>
          <h1>Участок надзора</h1>
          <p className="sk-supervision__hello">
            {user ? `${user.full_name}, ` : ""}на контроле {totals.objects}{" "}
            {plural(totals.objects, ["объект", "объекта", "объектов"])}
          </p>
        </div>
        <Link to="/supervision/queue" className="sk-button">
          Разобрать очередь — {totals.requires_decision}
        </Link>
      </header>

      <div className="sk-supervision__summary">
        <div className="sk-metric sk-metric--wide">
          <span className="sk-metric__label">Обработано системой</span>
          <strong>{totals.observations_total}</strong>
          <span className="sk-metric__sub">
            снимков всего, из них {totals.observations_last_30_days} за последние 30 дней
          </span>
        </div>
        <div className="sk-metric sk-metric--accent">
          <span className="sk-metric__label">Требует вашего решения</span>
          <strong>{totals.requires_decision}</strong>
          <span className="sk-metric__sub">
            {totals.critical > 0 ? `${totals.critical} критичных` : "критичных нет"}
          </span>
        </div>
        <div className="sk-metric">
          <span className="sk-metric__label">Отстают от графика</span>
          <strong>{totals.objects_behind}</strong>
          <span className="sk-metric__sub">из {totals.objects} объектов</span>
        </div>
        <div className="sk-metric">
          <span className="sk-metric__label">Ждут подтверждения</span>
          <strong>{totals.awaiting_confirmation}</strong>
          <span className="sk-metric__sub">закрыты системой, нужен человек</span>
        </div>
      </div>

      {data.stale_objects.length > 0 && (
        <div className="sk-panel sk-supervision__stale">
          <h2>Вне контроля</h2>
          <p className="sk-table__muted">
            По этим объектам нет подтверждённых снимков дольше {data.stale_after_days} дней.
            Отсутствие отклонений здесь не означает, что всё в порядке, — означает, что там
            ничего не проверяли.
          </p>
          <ul>
            {data.stale_objects.map((item) => (
              <li key={item.project_id}>
                <Link to={`/projects/${item.project_id}`}>{item.name}</Link> —{" "}
                {item.has_confirmed_dates
                  ? lastSeen(item.days_since_last_observation)
                  : "ни одного снимка с подтверждённой датой"}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="sk-object-list">{data.objects.map(renderRow)}</div>

      <p className="sk-demo-note">
        Объекты собраны из выданного набора снимков: кадры разложены по площадкам вручную,
        даты взяты со штампов на самих фотографиях и сдвинуты вперёд, чтобы объекты были
        живыми на сегодняшнюю дату. Плановые сроки демонстрационные — календарного плана
        заказчика в материалах нет.
      </p>
    </div>
  );
}
