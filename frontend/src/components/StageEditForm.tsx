import { useState } from "react";
import type {
  StageDetail,
  StageWritePayload,
  VocabularyClassSummary,
  ZoneDetail,
} from "../api";
import "./StageEditForm.css";

interface Props {
  mode: "create" | "edit";
  stageId?: string;
  initial: StageDetail | null;
  defaultZoneId: string;
  zones: ZoneDetail[];
  otherStages: StageDetail[];
  vocabulary: VocabularyClassSummary[];
  busy: boolean;
  error: string | null;
  onSubmit: (payload: StageWritePayload) => void;
  onCancel: () => void;
  onDelete?: () => void;
}

interface RequiredRow {
  class_key: string;
  min_quantity: number;
}

/**
 * Форма создания/редактирования этапа календарного плана — как обычные поля формы,
 * без drag-resize баров на диаграмме (это на порядок увеличило бы объём работы ради
 * второстепенного удобства). Используется в режиме редактирования на SchedulePage.tsx,
 * по аналогии с формами редактора карты (Zone/Camera).
 */
export function StageEditForm({
  mode,
  stageId,
  initial,
  defaultZoneId,
  zones,
  otherStages,
  vocabulary,
  busy,
  error,
  onSubmit,
  onCancel,
  onDelete,
}: Props) {
  const [workName, setWorkName] = useState(initial?.work_name ?? "");
  const [workCode, setWorkCode] = useState(initial?.work_code ?? "");
  const [zoneId, setZoneId] = useState(initial?.zone_id ?? defaultZoneId);
  const [startDate, setStartDate] = useState(initial?.start_date ?? "");
  const [endDate, setEndDate] = useState(initial?.end_date ?? "");
  const [parentId, setParentId] = useState(initial?.parent_id ?? "");
  const [predecessorIds, setPredecessorIds] = useState<string[]>(initial?.predecessor_ids ?? []);
  const [technologyAssumption, setTechnologyAssumption] = useState(initial?.technology_assumption ?? "");
  const [required, setRequired] = useState<RequiredRow[]>(
    initial?.required.map((r) => ({ class_key: r.class_key, min_quantity: r.min_quantity })) ?? [],
  );
  const [allowed, setAllowed] = useState<string[]>(initial?.allowed ?? []);
  const [alternativesNote, setAlternativesNote] = useState(initial?.alternatives_note ?? "");
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const togglePredecessor = (id: string) => {
    setPredecessorIds((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));
  };

  const toggleAllowed = (key: string) => {
    setAllowed((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  };

  const addRequiredRow = () => {
    const firstUnused = vocabulary.find((v) => !required.some((r) => r.class_key === v.key));
    setRequired((prev) => [...prev, { class_key: firstUnused?.key ?? vocabulary[0]?.key ?? "", min_quantity: 1 }]);
  };

  const updateRequiredRow = (index: number, patch: Partial<RequiredRow>) => {
    setRequired((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const removeRequiredRow = (index: number) => {
    setRequired((prev) => prev.filter((_, i) => i !== index));
  };

  const valid =
    workName.trim().length > 0 && zoneId && startDate && endDate && endDate >= startDate && required.every((r) => r.class_key);

  const handleSubmit = () => {
    if (!valid) return;
    onSubmit({
      work_name: workName.trim(),
      work_code: workCode.trim(),
      zone_id: zoneId,
      start_date: startDate,
      end_date: endDate,
      parent_id: parentId || null,
      predecessor_ids: predecessorIds,
      technology_assumption: technologyAssumption.trim(),
      required: required.map((r) => ({ class_key: r.class_key, min_quantity: r.min_quantity })),
      allowed,
      alternatives_note: alternativesNote.trim(),
    });
  };

  return (
    <div className="sk-stage-form">
      <div className="sk-stage-form__section">
        <label>
          Название работы
          <input type="text" value={workName} onChange={(e) => setWorkName(e.target.value)} autoFocus />
        </label>
        <label>
          Код работы (необязательно)
          <input type="text" value={workCode} onChange={(e) => setWorkCode(e.target.value)} />
        </label>
        <label>
          Зона
          <select value={zoneId} onChange={(e) => setZoneId(e.target.value)}>
            {zones.map((z) => (
              <option key={z.zone_id} value={z.zone_id}>
                {z.name}
              </option>
            ))}
          </select>
        </label>
        <div className="sk-stage-form__row">
          <label>
            Дата начала
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label>
            Дата окончания
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
        </div>
        {endDate && startDate && endDate < startDate && (
          <p className="sk-stage-form__error">Дата окончания не может быть раньше даты начала.</p>
        )}
      </div>

      <div className="sk-stage-form__section">
        <label>
          Родительская работа
          <select value={parentId} onChange={(e) => setParentId(e.target.value)}>
            <option value="">— нет —</option>
            {otherStages
              .filter((s) => s.stage_id !== stageId)
              .map((s) => (
                <option key={s.stage_id} value={s.stage_id}>
                  {s.work_name}
                </option>
              ))}
          </select>
        </label>
        {otherStages.length > 0 && (
          <div className="sk-stage-form__field">
            <span className="sk-stage-form__field-label">Предшественники</span>
            <div className="sk-stage-form__checklist">
              {otherStages
                .filter((s) => s.stage_id !== stageId)
                .map((s) => (
                  <label key={s.stage_id} className="sk-checkbox">
                    <input
                      type="checkbox"
                      checked={predecessorIds.includes(s.stage_id)}
                      onChange={() => togglePredecessor(s.stage_id)}
                    />
                    {s.work_name}
                  </label>
                ))}
            </div>
          </div>
        )}
      </div>

      <div className="sk-stage-form__section">
        <label>
          Технологическое допущение
          <textarea
            value={technologyAssumption}
            onChange={(e) => setTechnologyAssumption(e.target.value)}
            rows={2}
          />
        </label>
      </div>

      <div className="sk-stage-form__section">
        <span className="sk-stage-form__field-label">Требуемая техника</span>
        <div className="sk-stage-form__required-list">
          {required.map((row, index) => (
            <div key={index} className="sk-stage-form__required-row">
              <select value={row.class_key} onChange={(e) => updateRequiredRow(index, { class_key: e.target.value })}>
                {vocabulary.map((v) => (
                  <option key={v.key} value={v.key}>
                    {v.label_ru}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={1}
                value={row.min_quantity}
                onChange={(e) => updateRequiredRow(index, { min_quantity: Math.max(1, Number(e.target.value)) })}
              />
              <button type="button" className="sk-button sk-button--secondary" onClick={() => removeRequiredRow(index)}>
                ✕
              </button>
            </div>
          ))}
        </div>
        <button type="button" className="sk-button sk-button--secondary" onClick={addRequiredRow} disabled={vocabulary.length === 0}>
          + Добавить технику
        </button>
      </div>

      <div className="sk-stage-form__section">
        <span className="sk-stage-form__field-label">Допустимо сверх плана</span>
        <div className="sk-stage-form__checklist">
          {vocabulary.map((v) => (
            <label key={v.key} className="sk-checkbox">
              <input type="checkbox" checked={allowed.includes(v.key)} onChange={() => toggleAllowed(v.key)} />
              {v.label_ru}
            </label>
          ))}
        </div>
        <label>
          Примечание об альтернативах
          <textarea value={alternativesNote} onChange={(e) => setAlternativesNote(e.target.value)} rows={2} />
        </label>
      </div>

      {error && <p className="sk-stage-form__error">{error}</p>}

      <div className="sk-stage-form__actions">
        <button type="button" className="sk-button" disabled={!valid || busy} onClick={handleSubmit}>
          {busy ? "Сохраняем…" : mode === "create" ? "Создать этап" : "Сохранить"}
        </button>
        <button type="button" className="sk-button sk-button--secondary" onClick={onCancel} disabled={busy}>
          Отмена
        </button>
        {mode === "edit" && onDelete && !confirmingDelete && (
          <button
            type="button"
            className="sk-button sk-settings-danger__trigger"
            onClick={() => setConfirmingDelete(true)}
            disabled={busy}
          >
            Удалить этап
          </button>
        )}
        {mode === "edit" && onDelete && confirmingDelete && (
          <span className="sk-stage-form__confirm">
            Точно удалить?
            <button type="button" className="sk-button sk-settings-danger__confirm-btn" onClick={onDelete} disabled={busy}>
              Да
            </button>
            <button type="button" className="sk-button sk-button--secondary" onClick={() => setConfirmingDelete(false)}>
              Нет
            </button>
          </span>
        )}
      </div>
    </div>
  );
}
