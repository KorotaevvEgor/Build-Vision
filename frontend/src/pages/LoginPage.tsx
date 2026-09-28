import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { ApiError } from "../api";
import "./LoginPage.css";

export function LoginPage() {
  const { user, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  // Придерживаем переход после успешного логина, иначе контекст пользователя
  // обновляется мгновенно и анимация подтверждения не успевает проиграться.
  const [holdRedirect, setHoldRedirect] = useState(false);

  if (user && !holdRedirect) {
    // После входа пользователь всегда попадает на выбор проекта, а не возвращается
    // на страницу, с которой его раньше разлогинило (см. план).
    return <Navigate to="/projects" replace />;
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    setHoldRedirect(true);
    try {
      await login(username, password);
      setSuccess(true);
      window.setTimeout(() => setHoldRedirect(false), 850);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Неверный логин или пароль");
      } else {
        setError("Не удалось войти — попробуйте ещё раз");
      }
      setLoading(false);
      setHoldRedirect(false);
    }
  };

  return (
    <div className="sk-login">
      <div className="sk-login__glow sk-login__glow--one" aria-hidden="true" />
      <div className="sk-login__glow sk-login__glow--two" aria-hidden="true" />
      <div className="sk-login__grid-overlay" aria-hidden="true" />

      <div className={`sk-login__card${success ? " sk-login__card--success" : ""}`}>
        <aside className="sk-login__cover" aria-hidden="true">
          <div className="sk-login__cover-image" />
          <div className="sk-login__cover-veil" />
          <div className="sk-login__cover-content">
            <span className="sk-login__cover-badge">AI-контроль строительства</span>
            <p className="sk-login__cover-text">
              Видим каждую единицу техники, каждое отклонение и каждый день графика.
            </p>
          </div>
        </aside>

        <div className="sk-login__panel">
          <form className="sk-login__form" onSubmit={onSubmit}>
            <div className="sk-login__header">
              <span className="sk-login__eyebrow">BuildVision</span>
              <h1 className="sk-login__title">Авторизация</h1>
              <p className="sk-login__hint">Войдите, чтобы продолжить работу с проектами</p>
            </div>

            <div className="sk-login__field">
              <label htmlFor="username">Логин</label>
              <input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder="Введите логин"
                disabled={loading}
                required
              />
            </div>

            <div className="sk-login__field">
              <label htmlFor="password">Пароль</label>
              <div className="sk-login__password">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder="Введите пароль"
                  disabled={loading}
                  required
                />
                <button
                  type="button"
                  className="sk-login__password-toggle"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 3l18 18M10.6 10.7a2 2 0 0 0 2.8 2.8" />
                      <path d="M9.4 5.2A9.6 9.6 0 0 1 12 4.9c5 0 9 4.6 9 7.1 0 1-.7 2.4-1.9 3.7M6.3 6.8C4 8.3 3 10.6 3 12c0 2.5 4 7.1 9 7.1 1.4 0 2.7-.3 3.8-.9" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 12s3.6-7 9-7 9 7 9 7-3.6 7-9 7-9-7-9-7Z" />
                      <circle cx="12" cy="12" r="2.6" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            <div className={`sk-login__error${error ? " sk-login__error--visible" : ""}`} role="alert">
              {error}
            </div>

            <button
              type="submit"
              className={`sk-login__submit${loading ? " sk-login__submit--loading" : ""}${success ? " sk-login__submit--success" : ""}`}
              disabled={loading}
            >
              <span className="sk-login__submit-label">
                {success ? "Добро пожаловать" : loading ? "Входим…" : "Войти"}
              </span>
              {loading && !success && <span className="sk-login__spinner" aria-hidden="true" />}
            </button>

            <p className="sk-login__footer">Доступ выдаёт администратор проекта</p>
          </form>
        </div>
      </div>
    </div>
  );
}
