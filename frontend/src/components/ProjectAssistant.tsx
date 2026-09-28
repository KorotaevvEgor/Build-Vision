import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, askProjectAssistant } from "../api";
import type { AssistantMessage, ProjectId } from "../api";
import "./ProjectAssistant.css";

const QUICK_QUESTIONS = [
  "На каком этапе проект?",
  "Сколько техники не хватает?",
  "Когда планируется завершение?",
];

interface ProjectAssistantProps {
  projectId: ProjectId;
  projectName: string;
}

/**
 * Плавающий чат с ИИ-ассистентом проекта. Отвечает только по данным конкретного
 * проекта (см. backend/app/assistant.py) — история диалога живёт только в
 * состоянии компонента и пропадает при перезагрузке страницы, отдельного
 * хранилища для демонстрационного чата намеренно нет.
 */
export function ProjectAssistant({ projectId, projectName }: ProjectAssistantProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, loading, open]);

  const send = async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || loading) return;
    setError(null);
    const history = messages;
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setInput("");
    setLoading(true);
    try {
      const result = await askProjectAssistant(projectId, trimmed, history);
      if (result.available) {
        setMessages((prev) => [...prev, { role: "assistant", content: result.answer }]);
      } else {
        setError(result.error ?? "Ассистент временно недоступен");
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Слишком много вопросов подряд — попробуйте через пару минут");
      } else {
        setError("Не удалось получить ответ — попробуйте ещё раз");
      }
    } finally {
      setLoading(false);
    }
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void send(input);
  };

  return (
    <>
      <button
        type="button"
        className={`sk-assistant-fab${open ? " sk-assistant-fab--open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Закрыть ИИ-ассистента" : "Открыть ИИ-ассистента"}
        aria-expanded={open}
      >
        {open ? (
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8A2.5 2.5 0 0 1 17.5 16H10l-4.5 4v-4H6.5A2.5 2.5 0 0 1 4 13.5Z" />
            <circle cx="9" cy="9.5" r="1" fill="currentColor" stroke="none" />
            <circle cx="12.5" cy="9.5" r="1" fill="currentColor" stroke="none" />
            <circle cx="16" cy="9.5" r="1" fill="currentColor" stroke="none" />
          </svg>
        )}
      </button>

      {open && (
        <div className="sk-assistant-panel" role="dialog" aria-label="ИИ-ассистент проекта">
          <div className="sk-assistant-panel__header">
            <div>
              <div className="sk-assistant-panel__title">ИИ-ассистент проекта</div>
              <div className="sk-assistant-panel__subtitle" title={projectName}>
                {projectName}
              </div>
            </div>
            <button
              type="button"
              className="sk-assistant-panel__close"
              onClick={() => setOpen(false)}
              aria-label="Закрыть"
            >
              ✕
            </button>
          </div>

          <div className="sk-assistant-panel__body" ref={listRef}>
            {messages.length === 0 && (
              <div className="sk-assistant-empty">
                Спросите об этапе, технике, сроках или отклонениях этого проекта.
              </div>
            )}
            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={`sk-assistant-msg sk-assistant-msg--${msg.role}`}
              >
                {msg.content}
              </div>
            ))}
            {loading && (
              <div className="sk-assistant-msg sk-assistant-msg--assistant sk-assistant-msg--typing">
                <span />
                <span />
                <span />
              </div>
            )}
            {error && <div className="sk-assistant-error">{error}</div>}
          </div>

          <div className="sk-assistant-panel__chips">
            {QUICK_QUESTIONS.map((q) => (
              <button
                key={q}
                type="button"
                className="sk-assistant-chip"
                onClick={() => void send(q)}
                disabled={loading}
              >
                {q}
              </button>
            ))}
          </div>

          <form className="sk-assistant-panel__input" onSubmit={onSubmit}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Задайте вопрос по проекту…"
              disabled={loading}
              maxLength={1000}
            />
            <button type="submit" disabled={loading || !input.trim()} aria-label="Отправить">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 12l16-7-7 16-2-7-7-2Z" />
              </svg>
            </button>
          </form>
        </div>
      )}
    </>
  );
}
