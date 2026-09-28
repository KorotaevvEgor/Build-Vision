import { useEffect, useState } from "react";
import { useAuth } from "../AuthContext";
import {
  deployModelVersion,
  fetchLearningStats,
  trainModelVersion,
  type LearningStatsResponse,
  type ModelVersionSummary,
} from "../api";
import "./LearningCenterPage.css";

const STATUS_LABEL: Record<ModelVersionSummary["status"], string> = {
  production: "Рабочая версия",
  candidate: "Кандидат",
  archived: "Архив",
};

function MetricsBlock({ metrics }: { metrics: ModelVersionSummary["metrics"] }) {
  if (!metrics.available) {
    return <p className="sk-empty-state">{metrics.reason ?? "Метрики недоступны."}</p>;
  }
  return (
    <div>
      <p className="sk-table__muted">
        Accuracy: <strong>{((metrics.accuracy ?? 0) * 100).toFixed(0)}%</strong> (train:{" "}
        {metrics.train_count}, test: {metrics.test_count})
      </p>
      {metrics.per_class && metrics.per_class.length > 0 && (
        <table className="sk-table">
          <thead>
            <tr>
              <th>Класс</th>
              <th>Precision</th>
              <th>Recall</th>
              <th>Примеров</th>
            </tr>
          </thead>
          <tbody>
            {metrics.per_class.map((row) => (
              <tr key={row.class_key}>
                <td>{row.class_key}</td>
                <td>{(row.precision * 100).toFixed(0)}%</td>
                <td>{(row.recall * 100).toFixed(0)}%</td>
                <td>{row.support}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {metrics.note && <p className="sk-table__muted">{metrics.note}</p>}
    </div>
  );
}

export function LearningCenterPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [stats, setStats] = useState<LearningStatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [trainMessage, setTrainMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = () => {
    fetchLearningStats()
      .then(setStats)
      .catch((err: Error) => setError(err.message));
  };

  useEffect(reload, []);

  const onTrain = async () => {
    setBusy(true);
    setTrainMessage(null);
    try {
      const result = await trainModelVersion();
      setTrainMessage(
        result.started
          ? "Обучение запущено в фоне — обновите страницу через минуту, чтобы увидеть кандидата."
          : (result.reason ?? "Не удалось запустить обучение."),
      );
    } catch (err) {
      setTrainMessage(err instanceof Error ? err.message : "Не удалось запустить обучение.");
    } finally {
      setBusy(false);
    }
  };

  const onDeploy = async (versionId: number) => {
    setBusy(true);
    try {
      await deployModelVersion(versionId);
      reload();
    } catch (err) {
      setTrainMessage(err instanceof Error ? err.message : "Не удалось опубликовать версию.");
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return <div className="sk-panel sk-panel--error">Не удалось загрузить данные: {error}</div>;
  }
  if (!stats) {
    return <div className="sk-panel">Загрузка…</div>;
  }
  if (!stats.available) {
    return (
      <div className="sk-learning-page">
        <h1>Центр обучения AI</h1>
        <div className="sk-panel">
          <p className="sk-empty-state">БД временно недоступна — данные обучения недоступны.</p>
        </div>
      </div>
    );
  }

  const production = stats.production_version ?? null;
  const candidates = stats.candidate_versions ?? [];

  return (
    <div className="sk-learning-page">
      <h1>Центр обучения AI</h1>
      <p className="sk-demo-note">
        Лёгкий классификатор-корректор поверх CLIP-эмбеддингов, обучаемый на коррекциях инженера
        (неоднозначные или низкоуверенные детекции на экране «Камера — AI-анализ»). Коррекции —
        единственный в проекте реально размеченный человеком датасет, поэтому метрики ниже
        измерены на отложенной части самих коррекций (train/test-разбиение), а не на отдельном
        эталонном наборе — его в проекте нет.
      </p>

      <div className="sk-learning-page__stats">
        <div className="sk-panel sk-metric-card">
          <div className="sk-metric-card__value">{stats.correction_count}</div>
          <div className="sk-metric-card__label">Коррекций всего</div>
        </div>
        <div className="sk-panel sk-metric-card">
          <div className="sk-metric-card__value">{stats.confirmation_count}</div>
          <div className="sk-metric-card__label">Подтверждений</div>
        </div>
        <div className="sk-panel sk-metric-card">
          <div className="sk-metric-card__value">{stats.fixed_error_count}</div>
          <div className="sk-metric-card__label">Исправленных ошибок</div>
        </div>
        <div className="sk-panel sk-metric-card">
          <div className="sk-metric-card__value">{stats.not_equipment_count}</div>
          <div className="sk-metric-card__label">Помечено «не техника»</div>
        </div>
      </div>

      <div className="sk-panel" style={{ marginTop: "var(--sk-space-5)" }}>
        <h2>Рабочая версия</h2>
        {production ? (
          <>
            <p className="sk-table__muted">
              {production.version_label} · обучена{" "}
              {production.trained_at ? new Date(production.trained_at).toLocaleString("ru-RU") : "—"} ·
              коррекций использовано: {production.training_sample_count}
            </p>
            <MetricsBlock metrics={production.metrics} />
          </>
        ) : (
          <p className="sk-empty-state">Рабочая версия ещё не опубликована — используется исходная логика confusable-пар.</p>
        )}
      </div>

      {isAdmin && (
        <div className="sk-panel" style={{ marginTop: "var(--sk-space-5)" }}>
          <h2>Обучение</h2>
          <button type="button" className="sk-button" onClick={onTrain} disabled={busy}>
            {busy ? "Выполняется…" : "Запустить обучение"}
          </button>
          {trainMessage && <p className="sk-table__muted" style={{ marginTop: "var(--sk-space-2)" }}>{trainMessage}</p>}
        </div>
      )}

      <div className="sk-panel" style={{ marginTop: "var(--sk-space-5)" }}>
        <h2>Кандидаты</h2>
        {candidates.length === 0 && <p className="sk-empty-state">Кандидатов пока нет.</p>}
        {candidates.map((candidate) => (
          <div key={candidate.id} className="sk-learning-page__candidate">
            <div className="sk-learning-page__candidate-header">
              <h3>
                {candidate.version_label} <span className="sk-table__muted">({STATUS_LABEL[candidate.status]})</span>
              </h3>
              {isAdmin && (
                <button
                  type="button"
                  className="sk-button sk-button--secondary"
                  onClick={() => onDeploy(candidate.id)}
                  disabled={busy}
                >
                  Опубликовать как рабочую
                </button>
              )}
            </div>
            <p className="sk-table__muted">
              Обучен {candidate.trained_at ? new Date(candidate.trained_at).toLocaleString("ru-RU") : "—"} ·
              коррекций использовано: {candidate.training_sample_count}
            </p>
            <MetricsBlock metrics={candidate.metrics} />
          </div>
        ))}
      </div>
    </div>
  );
}
