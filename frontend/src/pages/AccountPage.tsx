import { useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useAuth } from "../AuthContext";
import { useTheme } from "../ThemeContext";
import {
  ApiError,
  avatarUrl,
  changePassword,
  deleteAvatar,
  logoutAllSessions,
  updateProfile,
  uploadAvatar,
} from "../api";
import "./AccountPage.css";

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AccountPage() {
  const { user, updateUser, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();

  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [position, setPosition] = useState(user?.position ?? "");
  const [positionSaveState, setPositionSaveState] = useState<"idle" | "saving" | "saved">("idle");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordSuccess, setPasswordSuccess] = useState(false);
  const [passwordBusy, setPasswordBusy] = useState(false);

  const [logoutAllBusy, setLogoutAllBusy] = useState(false);
  const [logoutAllConfirm, setLogoutAllConfirm] = useState(false);

  if (!user) return null;

  const handleAvatarFile = async (file: File) => {
    if (!file.type.startsWith("image/")) {
      setAvatarError("Ожидается изображение (JPG, PNG или WebP)");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setAvatarError("Файл больше 5 МБ");
      return;
    }
    setAvatarBusy(true);
    setAvatarError(null);
    try {
      const updated = await uploadAvatar(file);
      updateUser(updated);
    } catch (err) {
      setAvatarError(err instanceof Error ? err.message : "Не удалось загрузить фото");
    } finally {
      setAvatarBusy(false);
    }
  };

  const onFileInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void handleAvatarFile(file);
  };

  const removeAvatar = async () => {
    setAvatarBusy(true);
    setAvatarError(null);
    try {
      const updated = await deleteAvatar();
      updateUser(updated);
    } catch (err) {
      setAvatarError(err instanceof Error ? err.message : "Не удалось удалить фото");
    } finally {
      setAvatarBusy(false);
    }
  };

  const savePosition = async () => {
    if (position.trim() === user.position) return;
    setPositionSaveState("saving");
    try {
      const updated = await updateProfile({ position: position.trim() });
      updateUser(updated);
      setPositionSaveState("saved");
    } catch {
      setPositionSaveState("idle");
    }
  };

  const onChangePassword = async (event: FormEvent) => {
    event.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(false);
    if (newPassword !== confirmPassword) {
      setPasswordError("Новый пароль и подтверждение не совпадают");
      return;
    }
    setPasswordBusy(true);
    try {
      await changePassword(currentPassword, newPassword);
      setPasswordSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      if (err instanceof ApiError) {
        setPasswordError(err.message.replace(/^\d+ [^:]+:\s*/, "") || "Не удалось сменить пароль");
      } else {
        setPasswordError("Не удалось сменить пароль");
      }
    } finally {
      setPasswordBusy(false);
    }
  };

  const onLogoutAll = async () => {
    if (!logoutAllConfirm) {
      setLogoutAllConfirm(true);
      return;
    }
    setLogoutAllBusy(true);
    try {
      await logoutAllSessions();
    } finally {
      // Текущая сессия тоже завершена сервером — локально выходим в любом случае.
      await logout();
    }
  };

  const currentAvatarUrl = avatarUrl(user);

  return (
    <div className="sk-account-page">
      <h1>Настройки профиля</h1>

      <div className="sk-panel sk-account-section">
        <h2>Профиль</h2>
        <div className="sk-account-profile">
          <div
            className={`sk-account-avatar${dragOver ? " sk-account-avatar--drag" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const file = e.dataTransfer.files?.[0];
              if (file) void handleAvatarFile(file);
            }}
          >
            {currentAvatarUrl ? (
              <img className="sk-account-avatar__img" src={currentAvatarUrl} alt="" />
            ) : (
              <span className="sk-account-avatar__placeholder">
                {user.full_name.slice(0, 1).toUpperCase()}
              </span>
            )}
            {avatarBusy && <span className="sk-account-avatar__overlay">…</span>}
          </div>
          <div className="sk-account-avatar__actions">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              hidden
              onChange={onFileInputChange}
            />
            <button
              type="button"
              className="sk-button sk-button--secondary"
              onClick={() => fileInputRef.current?.click()}
              disabled={avatarBusy}
            >
              {currentAvatarUrl ? "Заменить фото" : "Загрузить фото"}
            </button>
            {currentAvatarUrl && (
              <button
                type="button"
                className="sk-button sk-button--secondary"
                onClick={() => void removeAvatar()}
                disabled={avatarBusy}
              >
                Удалить
              </button>
            )}
            <p className="sk-field__hint">
              Перетащите изображение сюда или выберите файл — JPG, PNG, WebP, до 5 МБ.
            </p>
            {avatarError && <p className="sk-account-error">{avatarError}</p>}
          </div>
        </div>

        <dl className="sk-account-info">
          <div>
            <dt>ФИО</dt>
            <dd>{user.full_name}</dd>
          </div>
          <div>
            <dt>Логин</dt>
            <dd>{user.username}</dd>
          </div>
          <div>
            <dt>Роль</dt>
            <dd>{user.role_label}</dd>
          </div>
          <div>
            <dt>В системе с</dt>
            <dd>{formatDateTime(user.date_joined)}</dd>
          </div>
          <div>
            <dt>Последний вход</dt>
            <dd>{formatDateTime(user.last_login)}</dd>
          </div>
        </dl>

        <div className="sk-field sk-account-position">
          <label htmlFor="position">Должность</label>
          <div className="sk-account-position__row">
            <input
              id="position"
              value={position}
              onChange={(e) => {
                setPosition(e.target.value);
                setPositionSaveState("idle");
              }}
              placeholder="Например, «Руководитель проекта»"
              maxLength={150}
            />
            <button
              type="button"
              className="sk-button sk-button--secondary"
              disabled={position.trim() === user.position || positionSaveState === "saving"}
              onClick={() => void savePosition()}
            >
              {positionSaveState === "saving" ? "Сохраняем…" : "Сохранить"}
            </button>
          </div>
          {positionSaveState === "saved" && position.trim() === user.position && (
            <p className="sk-field__hint">Сохранено.</p>
          )}
          <p className="sk-field__hint">
            ФИО, логин и роль меняются администратором через Django admin.
          </p>
        </div>
      </div>

      <div className="sk-panel sk-account-section">
        <h2>Оформление</h2>
        <p className="sk-table__muted">
          Настройка хранится на этом устройстве и не влияет на других пользователей.
        </p>
        <div className="sk-account-theme">
          <button
            type="button"
            className={`sk-account-theme__option${theme === "dark" ? " sk-account-theme__option--active" : ""}`}
            onClick={() => theme !== "dark" && toggleTheme()}
          >
            <span className="sk-account-theme__preview sk-account-theme__preview--dark" aria-hidden="true" />
            Тёмная
          </button>
          <button
            type="button"
            className={`sk-account-theme__option${theme === "light" ? " sk-account-theme__option--active" : ""}`}
            onClick={() => theme !== "light" && toggleTheme()}
          >
            <span className="sk-account-theme__preview sk-account-theme__preview--light" aria-hidden="true" />
            Светлая
          </button>
        </div>
      </div>

      <div className="sk-panel sk-account-section">
        <h2>Безопасность</h2>
        <form className="sk-account-password" onSubmit={onChangePassword}>
          <div className="sk-field">
            <label htmlFor="current-password">Текущий пароль</label>
            <input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              disabled={passwordBusy}
            />
          </div>
          <div className="sk-field">
            <label htmlFor="new-password">Новый пароль</label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              disabled={passwordBusy}
            />
          </div>
          <div className="sk-field">
            <label htmlFor="confirm-password">Подтверждение пароля</label>
            <input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              disabled={passwordBusy}
            />
          </div>
          {passwordError && <p className="sk-account-error">{passwordError}</p>}
          {passwordSuccess && <p className="sk-account-success">Пароль изменён.</p>}
          <button type="submit" className="sk-button" disabled={passwordBusy}>
            {passwordBusy ? "Сохраняем…" : "Сменить пароль"}
          </button>
        </form>

        <div className="sk-account-danger">
          <div>
            <strong>Завершить сеанс на всех устройствах</strong>
            <p className="sk-table__muted">
              Разлогинит все устройства, включая текущее — потребуется войти заново.
            </p>
          </div>
          <button
            type="button"
            className="sk-button sk-button--secondary"
            onClick={() => void onLogoutAll()}
            disabled={logoutAllBusy}
          >
            {logoutAllConfirm ? "Точно завершить всё?" : "Завершить всё"}
          </button>
        </div>
      </div>
    </div>
  );
}
