import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { ApiError } from "../api";
import brandLogo from "../assets/brand-logo.png";
import "./LoginPage.css";

export function LoginPage() {
  const { user, login } = useAuth();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (user) {
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Неверный логин или пароль"
          : "Не удалось связаться с сервером. Проверьте подключение и повторите вход.",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="sk-login-page">
      <div className="sk-login-page__brand">
        <img
          src={brandLogo}
          alt="BuildVision"
          className="sk-login-page__logo"
          width="900"
          height="660"
          fetchPriority="high"
        />
        <div className="sk-login-page__subtitle">Умный контроль стройки</div>
      </div>

      <form className="sk-panel" onSubmit={onSubmit}>
        <div className="sk-field">
          <label htmlFor="username">Логин</label>
          <input id="username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </div>
        <div className="sk-field">
          <label htmlFor="password">Пароль</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>
        {error && <p className="sk-login-page__error">{error}</p>}
        <button type="submit" className="sk-button sk-button--block" disabled={loading || !username || !password}>
          {loading ? "Входим…" : "Войти"}
        </button>
      </form>
    </div>
  );
}
