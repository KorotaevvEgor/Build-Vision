import { lazy } from "react";
import { PageLoader } from "./components/PageLoader";
import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext";
import { ProjectProvider } from "./ProjectContext";
import { Layout } from "./components/Layout";
import { AppShell } from "./components/AppShell";
const MapPage = lazy(() => import("./pages/MapPage").then(module => ({default:module.MapPage})));
const AnalysisPage = lazy(() => import("./pages/AnalysisPage").then(module => ({default:module.AnalysisPage})));
function LegacyScheduleRedirect(){const {search}=useLocation();return <Navigate to={`../schedule${search}`} replace/>;}
const ScheduleV2Page = lazy(() => import("./pages/ScheduleV2Page").then(module => ({default:module.ScheduleV2Page})));
const DocumentationPage = lazy(() => import("./pages/DocumentationPage").then(module => ({default:module.DocumentationPage})));
const LoginPage = lazy(() => import("./pages/LoginPage").then(module => ({default:module.LoginPage})));
const DashboardPage = lazy(() => import("./pages/DashboardPage").then(module => ({default:module.DashboardPage})));
const InsightsPage = lazy(() => import("./pages/InsightsPage").then(module => ({default:module.InsightsPage})));
const DeviationDetailPage = lazy(() => import("./pages/DeviationDetailPage").then(module => ({default:module.DeviationDetailPage})));
const ForecastExplanationPage = lazy(() => import("./pages/ForecastExplanationPage").then(module => ({default:module.ForecastExplanationPage})));
const LearningCenterPage = lazy(() => import("./pages/LearningCenterPage").then(module => ({default:module.LearningCenterPage})));
const CamerasPage = lazy(() => import("./pages/CamerasPage").then(module => ({default:module.CamerasPage})));
const CameraDetailPage = lazy(() => import("./pages/CameraDetailPage").then(module => ({default:module.CameraDetailPage})));
const ZoneEditorPage = lazy(() => import("./pages/ZoneEditorPage").then(module => ({default:module.ZoneEditorPage})));

const CorrectionBoardPage = lazy(() => import("./pages/CorrectionBoardPage").then(module => ({default:module.CorrectionBoardPage})));
const CorrectionTaskPage = lazy(() => import("./pages/CorrectionTaskPage").then(module => ({default:module.CorrectionTaskPage})));
const NotificationsPage = lazy(() => import("./pages/NotificationsPage").then(module => ({default:module.NotificationsPage})));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then(module => ({default:module.SettingsPage})));
const ProjectsPage = lazy(() => import("./pages/ProjectsPage").then(module => ({default:module.ProjectsPage})));
const CreateProjectPage = lazy(() => import("./pages/CreateProjectPage").then(module => ({default:module.CreateProjectPage})));
const AccountPage = lazy(() => import("./pages/AccountPage").then(module => ({default:module.AccountPage})));
const DemoPage = lazy(() => import("./pages/DemoPage").then(module => ({default:module.DemoPage})));
const PhotoAnalysisDemoPage = lazy(() => import("./pages/PhotoAnalysisDemoPage").then(module => ({default:module.PhotoAnalysisDemoPage})));
const SupervisionPage = lazy(() => import("./pages/SupervisionPage").then(module => ({default:module.SupervisionPage})));
const ReviewQueuePage = lazy(() => import("./pages/ReviewQueuePage").then(module => ({default:module.ReviewQueuePage})));

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading, bootError, retrySession } = useAuth();
  const location = useLocation();

  if (loading) {
    return <div className="sk-panel">Проверяем сессию…</div>;
  }
  if (bootError) return <div className="sk-panel sk-panel--error" role="alert">{bootError} <button type="button" onClick={retrySession}>Повторить загрузку</button></div>;
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
          <Route path="documentation" element={<PageLoader><DocumentationPage /></PageLoader>} />
          <Route path="login" element={<PageLoader><LoginPage /></PageLoader>} />
          {/* Единственный экран без авторизации: показать работу системы можно
              без выдачи доступа к проектам и чужим данным. */}
          <Route path="demo" element={<PageLoader><DemoPage /></PageLoader>} />
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
              <Route index element={<Navigate to="/projects" replace />} />
              <Route path="supervision" element={<PageLoader><SupervisionPage /></PageLoader>} />
              <Route path="supervision/queue" element={<PageLoader><ReviewQueuePage /></PageLoader>} />
              <Route path="projects" element={<PageLoader><ProjectsPage /></PageLoader>} />
              {/* Тот же сценарий разбора снимка, что и на публичной /demo, но встроен в рабочее
                  пространство без привязки к проекту -- удобно показать заказчику произвольный кадр. */}
              <Route path="demo-analysis" element={<PageLoader><PhotoAnalysisDemoPage /></PageLoader>} />
              <Route
                path="projects/new"
                element={
                  <RequireAdmin>
                    <PageLoader><CreateProjectPage /></PageLoader>
                  </RequireAdmin>
                }
              />
              {/* Глобальная страница настроек профиля, доступна независимо от выбранного проекта. */}
              <Route path="account" element={<PageLoader><AccountPage /></PageLoader>} />
              {/* Центр обучения AI — глобальная административная область, не привязана к проекту
                  (корректор обучен только на legacy-проекте, см. план, граница Learning). */}
              <Route
                path="system/learning"
                element={
                  <RequireAdmin>
                    <PageLoader><LearningCenterPage /></PageLoader>
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
              <Route index element={<PageLoader><DashboardPage /></PageLoader>} />
              <Route path="map" element={<PageLoader><MapPage /></PageLoader>} />
              <Route path="cameras" element={<PageLoader><CamerasPage /></PageLoader>} />
              <Route path="cameras/:cameraId" element={<PageLoader><CameraDetailPage /></PageLoader>} />
              {/* Разметка зон доступна для просмотра всем: участник должен видеть,
                  по какой геометрии система решала «работа или простой». Правка — только админу
                  (проверяется внутри страницы и на сервере). */}
              <Route path="cameras/:cameraId/zones" element={<PageLoader><ZoneEditorPage /></PageLoader>} />
              <Route path="analysis" element={<PageLoader><AnalysisPage /></PageLoader>} />
              <Route path="schedule" element={<PageLoader><ScheduleV2Page /></PageLoader>} />
              <Route path="schedule-v2" element={<LegacyScheduleRedirect />} />
              <Route path="forecast" element={<PageLoader><InsightsPage /></PageLoader>} />
              <Route path="forecast/why" element={<PageLoader><ForecastExplanationPage /></PageLoader>} />
              <Route path="analytics" element={<Navigate to="../forecast?tab=observations" replace/>} />
              <Route path="notifications/:deviationId" element={<PageLoader><DeviationDetailPage /></PageLoader>} />
              <Route path="notifications" element={<PageLoader><NotificationsPage /></PageLoader>} />
              <Route path="corrections" element={<PageLoader><CorrectionBoardPage /></PageLoader>} />
              <Route path="corrections/:taskId" element={<PageLoader><CorrectionTaskPage /></PageLoader>} />
              <Route path="settings" element={<PageLoader><SettingsPage /></PageLoader>} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
