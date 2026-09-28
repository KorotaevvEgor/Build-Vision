import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { useProject } from "../ProjectContext";
import {
  deleteProject,
  fetchRules,
  fetchSettings,
  updateSettings,
  type AppSettings,
  type RulesResponse,
  type VlmConfidenceLevel,
} from "../api";
import "./SettingsPage.css";

const ADMIN_URL = import.meta.env.VITE_ADMIN_URL ?? "/admin/";

type SaveState = "idle" | "saving" | "saved" | "error";

/** Подсказка о последствиях выбранного порога — чтобы настройка не была «числом без смысла». */
function describeConfidence(value: number): string {
  if (value <= 0.2) {
    return "Находится почти всё, но много ложных срабатываний на фоне: трубы, контейнеры, штабели материалов.";
  }
  if (value <= 0.35) {
    return "Сбалансированный режим: большая часть техники находится, ложные срабатывания единичны.";
  }
  if (value <= 0.6) {
    return "Осторожный режим: в отчёт попадает только уверенно распознанная техника, часть дальних машин теряется.";
  }
  return "Очень строгий режим: подтверждается только крупная техника на переднем плане.";
}

export function SettingsPage() {
  const { user, logout } = useAuth();
  const { projectId, project } = useProject();
  const navigate = useNavigate();
  const [rules, setRules] = useState<RulesResponse | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [confidence, setConfidence] = useState(0.25);
  const [vlmLevel, setVlmLevel] = useState<VlmConfidenceLevel>("high");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleteState, setDeleteState] = useState<"idle" | "deleting" | "error">("idle");
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSettings()
      .then((data) => {
        if (cancelled) return;
        setSettings(data);
        setConfidence(data.detector_confidence);
        setVlmLevel(data.autolabel_min_vlm_confidence);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (user?.role !== "admin") return;
    let cancelled = false;
    setRules(null);
    fetchRules(projectId)
      .then((data) => {
        if (!cancelled) setRules(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [user, projectId]);

  const save = async () => {
    setSaveState("saving");
    setError(null);
    try {
      const updated = await updateSettings({
        detector_confidence: confidence,
        autolabel_min_vlm_confidence: vlmLevel,
      });
      setSettings(updated);
      setSaveState("saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить настройки");
      setSaveState("error");
    }
  };

  if (!user) return null;

  const isAdmin = user.role === "admin";
  const changed =
    settings !== null &&
    (Math.abs(settings.detector_confidence - confidence) > 1e-6 ||
      settings.autolabel_min_vlm_confidence !== vlmLevel);

  const handleDeleteProject = async () => {
    setDeleteState("deleting");
    setDeleteError(null);
    try {
      await deleteProject(projectId, deleteConfirmText);
      navigate("/projects", { replace: true });
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Не удалось удалить проект");
      setDeleteState("error");
    }
  };

  return (
    <div className="sk-settings-page">
      <h1>Настройки проекта</h1>

      <div className="sk-settings-grid">
        <div className="sk-panel sk-settings-card">
          <h2>Профиль</h2>
          <p className="sk-table__muted">ФИО: {user.full_name}</p>
          <p className="sk-table__muted">Должность: {user.display_position}</p>
          <p className="sk-table__muted">Роль: {user.role_label}</p>
          <button type="button" className="sk-button sk-button--secondary sk-settings-card__action" onClick={() => void logout()}>
            Выйти
          </button>
        </div>

        {isAdmin && (
          <div className="sk-panel sk-settings-card">
            <h2>Системные параметры</h2>
            <p className="sk-table__muted">
              Справочники (классы техники, правила этапов, график, пользователи) — только через Django admin.
            </p>
            {rules && (
              <p className="sk-table__muted">
                Порог неоднозначности: <strong>{rules.ambiguity_margin}</strong> · путаемых пар: {rules.confusable_class_pairs.length} ·
                ограничений качества: {rules.known_limitations.length}
              </p>
            )}
            <a href={ADMIN_URL} target="_blank" rel="noreferrer" className="sk-button sk-settings-card__action">
              Открыть Django admin
            </a>
          </div>
        )}
      </div>

      {settings && (
        <div className="sk-panel sk-settings-sensitivity">
          <h2>Чувствительность распознавания</h2>
          <p className="sk-table__muted">
            Насколько уверенной должна быть находка, чтобы попасть в результат. Новый порог сразу действует
            для новых снимков, а уже загруженные переанализируются в фоне.
          </p>

          <div className="sk-settings-sensitivity__grid">
            <div className="sk-setting">
              <div className="sk-setting__head">
                <label htmlFor="confidence">Порог уверенности детектора</label>
                <strong className="sk-setting__value">{confidence.toFixed(2)}</strong>
              </div>
              <input
                id="confidence"
                type="range"
                min={settings.detector_confidence_min}
                max={settings.detector_confidence_max}
                step={0.05}
                value={confidence}
                disabled={!isAdmin}
                onChange={(e) => {
                  setConfidence(Number(e.target.value));
                  setSaveState("idle");
                }}
              />
              <div className="sk-setting__scale">
                <span>больше находок</span>
                <span>меньше ошибок</span>
              </div>
              <p className="sk-setting__hint">{describeConfidence(confidence)}</p>
            </div>

            <div className="sk-setting">
              <div className="sk-setting__head">
                <label htmlFor="vlm">Строгость при автоматической разметке</label>
              </div>
              <select
                id="vlm"
                value={vlmLevel}
                disabled={!isAdmin}
                onChange={(e) => {
                  setVlmLevel(e.target.value as VlmConfidenceLevel);
                  setSaveState("idle");
                }}
              >
                {settings.vlm_confidence_choices.map((choice) => (
                  <option key={choice.key} value={choice.key}>
                    {choice.label_ru}
                  </option>
                ))}
              </select>
              <p className="sk-setting__hint">
                Какой уверенности модели достаточно, чтобы принять класс в разметку. Строгий режим даёт
                меньше рамок, но исключает ошибки распознавания похожих классов.
              </p>
            </div>
          </div>

          {isAdmin ? (
            <div className="sk-setting__actions">
              <button
                type="button"
                className="sk-button"
                disabled={!changed || saveState === "saving"}
                onClick={() => void save()}
              >
                {saveState === "saving" ? "Сохраняем…" : "Сохранить"}
              </button>
              {saveState === "saved" && !changed && <span className="sk-setting__saved">Сохранено</span>}
              {saveState === "saved" && (
                <span className="sk-setting__note">Фотографии переанализируются в фоне.</span>
              )}
            </div>
          ) : (
            <p className="sk-table__muted">Изменять пороги может только администратор.</p>
          )}

          {!settings.stored_in_database && (
            <p className="sk-table__muted">Показаны значения по умолчанию: настройки ещё не сохранялись в базе.</p>
          )}
        </div>
      )}

      {error && <p className="sk-analysis-page__error">{error}</p>}

      {isAdmin && (
        <div className="sk-panel sk-settings-danger">
          <h2>Опасная зона</h2>
          {project.is_legacy ? (
            <p className="sk-table__muted">
              Это базовый (legacy) проект — он используется старыми версиями приложения и не может быть удалён.
            </p>
          ) : !deleteOpen ? (
            <>
              <p className="sk-table__muted">
                Удаление проекта необратимо: исчезнут все снимки, отклонения и история наблюдений. Отменить это действие нельзя.
              </p>
              <button
                type="button"
                className="sk-button sk-settings-danger__trigger"
                onClick={() => {
                  setDeleteOpen(true);
                  setDeleteConfirmText("");
                  setDeleteError(null);
                  setDeleteState("idle");
                }}
              >
                Удалить проект
              </button>
            </>
          ) : (
            <div className="sk-settings-danger__confirm">
              <p className="sk-table__muted">
                Чтобы подтвердить, введите название проекта целиком: <strong>{project.name}</strong>
              </p>
              <input
                type="text"
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
                placeholder={project.name}
                disabled={deleteState === "deleting"}
                autoFocus
              />
              <div className="sk-settings-danger__actions">
                <button
                  type="button"
                  className="sk-button sk-settings-danger__confirm-btn"
                  disabled={deleteConfirmText !== project.name || deleteState === "deleting"}
                  onClick={() => void handleDeleteProject()}
                >
                  {deleteState === "deleting" ? "Удаляем…" : "Удалить безвозвратно"}
                </button>
                <button
                  type="button"
                  className="sk-button sk-button--secondary"
                  disabled={deleteState === "deleting"}
                  onClick={() => setDeleteOpen(false)}
                >
                  Отмена
                </button>
              </div>
              {deleteError && <p className="sk-analysis-page__error">{deleteError}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
