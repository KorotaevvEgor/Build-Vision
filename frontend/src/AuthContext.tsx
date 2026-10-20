import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, fetchMe, login as apiLogin, logout as apiLogout, type CurrentUser } from "./api";

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  bootError: string | null;
  retrySession: () => void;
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
  const [bootError,setBootError]=useState<string|null>(null);
  const [attempt,setAttempt]=useState(0);

  useEffect(() => {
    // При открытии/обновлении страницы пробуем восстановить сессию по cookie —
    // без этого пользователь бы разлогинивался при каждом F5.
    let cancelled=false;
    setLoading(true);setBootError(null);
    fetchMe()
      .then(data=>!cancelled&&setUser(data))
      .catch((error:unknown) => {
        if(cancelled)return;
        if(error instanceof ApiError&&error.status===401)setUser(null);
        else setBootError(error instanceof Error?error.message:"Не удалось проверить соединение");
      })
      .finally(() => !cancelled&&setLoading(false));
    return ()=>{cancelled=true;};
  }, [attempt]);

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
    <AuthContext.Provider value={{ user, loading, bootError, retrySession: () => setAttempt(a=>a+1), login, logout, updateUser: setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth должен использоваться внутри AuthProvider");
  return ctx;
}
