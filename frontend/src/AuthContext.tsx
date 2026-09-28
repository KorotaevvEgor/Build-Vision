import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, fetchMe, login as apiLogin, logout as apiLogout, type CurrentUser } from "./api";

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /**
   * Подменяет данные пользователя в контексте без повторного запроса к `fetchMe` —
   * вызывается после успешных ответов updateProfile/uploadAvatar/deleteAvatar, чтобы
   * аватар/должность сразу обновились в топбаре/сайдбаре.
   */
  updateUser: (user: CurrentUser) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // При открытии/обновлении страницы пробуем восстановить сессию по cookie —
    // без этого пользователь бы разлогинивался при каждом F5.
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const loggedInUser = await apiLogin(username, password);
    setUser(loggedInUser);
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch (err) {
      // Даже если запрос на сервер не удался (сеть/БД), локально выходим —
      // не хотим запирать пользователя на экране из-за временной недоступности API.
      if (!(err instanceof ApiError)) throw err;
    } finally {
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, updateUser: setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth должен использоваться внутри AuthProvider");
  return ctx;
}
