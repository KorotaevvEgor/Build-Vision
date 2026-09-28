import type { ReactNode } from "react";
import { HashRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext";
import { ProjectProvider } from "./ProjectContext";
import { Shell } from "./components/Shell";
import { LoginPage } from "./pages/LoginPage";
import { HomePage } from "./pages/HomePage";
import { MapPage } from "./pages/MapPage";
import { CameraAnalysisPage } from "./pages/CameraAnalysisPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { CreateProjectPage } from "./pages/CreateProjectPage";
import { MorePage } from "./pages/MorePage";
import { CamerasListPage } from "./pages/CamerasListPage";
import { CameraDetailPage } from "./pages/CameraDetailPage";
import { SchedulePage } from "./pages/SchedulePage";
import { ForecastPage } from "./pages/ForecastPage";
import { ForecastExplanationPage } from "./pages/ForecastExplanationPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { SettingsPage } from "./pages/SettingsPage";

// HashRouter — а не BrowserRouter: приложение упаковано Capacitor'ом и грузится
// с локального файла (webDir), где серверной маршрутизации нет.

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

function App() {
  return (
    <AuthProvider>
      <HashRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <RequireAuth>
                <Outlet />
              </RequireAuth>
            }
          >
            {/* Новый вход и корневой адрес всегда ведут к списку проектов. */}
            <Route index element={<Navigate to="/projects" replace />} />
            <Route path="projects" element={<ProjectsPage />} />
            <Route
              path="projects/new"
              element={
                <RequireAdmin>
                  <CreateProjectPage />
                </RequireAdmin>
              }
            />
            <Route
              path="projects/:projectId"
              element={
                <ProjectProvider>
                  <Shell />
                </ProjectProvider>
              }
            >
              <Route index element={<HomePage />} />
              <Route path="cameras" element={<CamerasListPage />} />
              <Route path="cameras/:cameraId" element={<CameraDetailPage />} />
              <Route path="schedule" element={<SchedulePage />} />
              <Route path="forecast" element={<ForecastPage />} />
              <Route path="forecast/why" element={<ForecastExplanationPage />} />
              <Route path="analytics" element={<AnalyticsPage />} />
              <Route path="map" element={<MapPage />} />
              <Route path="analysis" element={<CameraAnalysisPage />} />
              <Route path="notifications" element={<NotificationsPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="profile" element={<ProfilePage />} />
              <Route path="more" element={<MorePage />} />
            </Route>
          </Route>
        </Routes>
      </HashRouter>
    </AuthProvider>
  );
}

export default App;
