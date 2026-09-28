import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext";
import { ProjectProvider } from "./ProjectContext";
import { Layout } from "./components/Layout";
import { AppShell } from "./components/AppShell";
import { MapPage } from "./pages/MapPage";
import { AnalysisPage } from "./pages/AnalysisPage";
import { SchedulePage } from "./pages/SchedulePage";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ForecastPage } from "./pages/ForecastPage";
import { ForecastExplanationPage } from "./pages/ForecastExplanationPage";
import { LearningCenterPage } from "./pages/LearningCenterPage";
import { CamerasPage } from "./pages/CamerasPage";
import { CameraDetailPage } from "./pages/CameraDetailPage";
import { ZoneEditorPage } from "./pages/ZoneEditorPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { CreateProjectPage } from "./pages/CreateProjectPage";
import { AccountPage } from "./pages/AccountPage";
import { DemoPage } from "./pages/DemoPage";
import { PhotoAnalysisDemoPage } from "./pages/PhotoAnalysisDemoPage";
import { SupervisionPage } from "./pages/SupervisionPage";
import { ReviewQueuePage } from "./pages/ReviewQueuePage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <div className="sk-panel">Проверяем сессию…</div>;
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== "admin") {
    return <Navigate to="/projects" replace />;
  }
  return <>{children}</>;
}

/**
 * Каркас для страниц вне конкретного проекта (список проектов, создание проекта,
 * центр обучения AI). Использует тот же сайдбар/топбар, что и страницы внутри
 * проекта, — только без проектного контекста, — чтобы вход в проект не выглядел
 * резким появлением структуры, которой раньше не было.
 */
function GlobalShell() {
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="login" element={<LoginPage />} />
          {/* Единственный экран без авторизации: показать работу системы можно
              без выдачи доступа к проектам и чужим данным. */}
          <Route path="demo" element={<DemoPage />} />
          <Route
            element={
              <RequireAuth>
                <Outlet />
              </RequireAuth>
            }
          >
            <Route element={<GlobalShell />}>
              {/* Рабочий день сотрудника надзора начинается не со списка проектов, а со
                  сводки по всем объектам: у него их десятки, и выбирать руками нечего. */}
              <Route index element={<Navigate to="/supervision" replace />} />
              <Route path="supervision" element={<SupervisionPage />} />
              <Route path="supervision/queue" element={<ReviewQueuePage />} />
              <Route path="projects" element={<ProjectsPage />} />
              {/* Тот же сценарий разбора снимка, что и на публичной /demo, но встроен в рабочее
                  пространство без привязки к проекту -- удобно показать заказчику произвольный кадр. */}
              <Route path="demo-analysis" element={<PhotoAnalysisDemoPage />} />
              <Route
                path="projects/new"
                element={
                  <RequireAdmin>
                    <CreateProjectPage />
                  </RequireAdmin>
                }
              />
              {/* Глобальная страница настроек профиля, доступна независимо от выбранного проекта. */}
              <Route path="account" element={<AccountPage />} />
              {/* Центр обучения AI — глобальная административная область, не привязана к проекту
                  (корректор обучен только на legacy-проекте, см. план, граница AI Learning). */}
              <Route
                path="system/learning"
                element={
                  <RequireAdmin>
                    <LearningCenterPage />
                  </RequireAdmin>
                }
              />
            </Route>
            <Route
              path="projects/:projectId"
              element={
                <ProjectProvider>
                  <Layout />
                </ProjectProvider>
              }
            >
              <Route index element={<DashboardPage />} />
              <Route path="map" element={<MapPage />} />
              <Route path="cameras" element={<CamerasPage />} />
              <Route path="cameras/:cameraId" element={<CameraDetailPage />} />
              {/* Разметка зон доступна для просмотра всем: участник должен видеть,
                  по какой геометрии система решала «работа или простой». Правка — только админу
                  (проверяется внутри страницы и на сервере). */}
              <Route path="cameras/:cameraId/zones" element={<ZoneEditorPage />} />
              <Route path="analysis" element={<AnalysisPage />} />
              <Route path="schedule" element={<SchedulePage />} />
              <Route path="forecast" element={<ForecastPage />} />
              <Route path="forecast/why" element={<ForecastExplanationPage />} />
              <Route path="analytics" element={<AnalyticsPage />} />
              <Route path="notifications" element={<NotificationsPage />} />
              <Route path="settings" element={<SettingsPage />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
