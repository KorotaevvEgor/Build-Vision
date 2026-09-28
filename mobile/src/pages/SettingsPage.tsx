import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { useProject } from "../ProjectContext";
import { deleteProject, fetchRules, fetchSettings, updateSettings, type AppSettings, type RulesResponse, type VlmConfidenceLevel } from "../api";
import "./SettingsPage.css";

type SaveState = "idle" | "saving" | "saved" | "error";

function describeConfidence(value: number): string {
  if (value <= 0.2) return "Находится почти всё, но много ложных срабатываний.";
  if (value <= 0.35) return "Сбалансированный режим.";
  if (value <= 0.6) return "Осторожный режим: часть дальних машин теряется.";
  return "Очень строгий режим.";
}

export function SettingsPage() {
  const { user } = useAuth();
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
    fetchRules(projectId)
      .then((data) => !cancelled && setRules(data))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [user, projectId]);

  const save = async () => {
    setSaveState("saving");
    setError(null);
    try {
      const updated = await updateSettings({ detector_confidence: confidence, autolabel_min_vlm_confidence: vlmLevel });
      setSettings(updated);
      setSaveState("saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить настройки");
      setSaveState("error");
    }
  };

  if (!user) return null;
  const isAdmin = user.role === "admin";
  const changed = settings !== null && (Math.abs(settings.detector_confidence - confidence) > 1e-6 || settings.autolabel_min_vlm_confidence !== vlmLevel);

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
    <div>
      <h1>Настройки проекта</h1>

      {rules && isAdmin && (
        <div className="sk-panel">
          <h2>Правила проекта</h2>
          <p className="sk-table__muted">
            Порог неоднозначности: <strong>{rules.ambiguity_margin}</strong> · путаемых пар: {rules.confusable_class_pairs.length}
          </p>
        </div>
      )}

      {settings && (
        <div className="sk-panel">
          <h2>Чувствительность распознавания</h2>
          <p className="sk-table__muted">Новый порог сразу действует для новых снимков.</p>

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
            <p className="sk-setting__hint">{describeConfidence(confidence)}</p>
          </div>

          <div className="sk-setting" style={{ marginTop: "var(--sk-space-3)" }}>
            <div className="sk-setting__head">
              <label htmlFor="vlm">Строгость автоматической разметки</label>
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
          </div>

          {isAdmin ? (
            <div className="sk-setting__actions">
              <button type="button" className="sk-button" disabled={!changed || saveState === "saving"} onClick={() => void save()}>
                {saveState === "saving" ? "Сохраняем…" : "Сохранить"}
              </button>
              {saveState === "saved" && !changed && <span className="sk-setting__saved">Сохранено</span>}
            </div>
          ) : (
            <p className="sk-table__muted">Изменять пороги может только администратор.</p>
          )}
        </div>
      )}

      {error && <p className="sk-panel sk-panel--error">{error}</p>}

      {isAdmin && (
        <div className="sk-panel sk-settings-danger">
          <h2>Опасная зона</h2>
          {project.is_legacy ? (
            <p className="sk-table__muted">Это базовый (legacy) проект — его нельзя удалить.</p>
          ) : !deleteOpen ? (
            <>
              <p className="sk-table__muted">Удаление проекта необратимо: исчезнут все снимки и история.</p>
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
                Введите название проекта целиком: <strong>{project.name}</strong>
              </p>
              <input
                type="text"
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
                placeholder={project.name}
                disabled={deleteState === "deleting"}
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
                <button type="button" className="sk-button sk-button--secondary" disabled={deleteState === "deleting"} onClick={() => setDeleteOpen(false)}>
                  Отмена
                </button>
              </div>
              {deleteError && <p className="sk-panel--error">{deleteError}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
