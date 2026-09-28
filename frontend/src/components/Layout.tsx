import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { useProject } from "../ProjectContext";
import { fetchDeviations } from "../api";
import { AppShell } from "./AppShell";

export function Layout() {
  const { projectId, project } = useProject();
  const [notificationCount, setNotificationCount] = useState(0);

  useEffect(() => {
    // В бейдже — число открытых отклонений (выявлено и назначено), а не число
    // сообщений: после введения жизненного цикла это требующая действия работа,
    // а не лента повторов. Сбрасываем при смене проекта, чтобы не показывать чужое число.
    let cancelled = false;
    setNotificationCount(0);
    fetchDeviations(projectId)
      .then((data) => {
        if (cancelled) return;
        setNotificationCount((data.counts.detected ?? 0) + (data.counts.assigned ?? 0));
      })
      .catch(() => {
        if (!cancelled) setNotificationCount(0);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <AppShell
      project={{
        id: projectId,
        name: project.name,
        address: project.address,
        latitude: project.latitude,
        longitude: project.longitude,
      }}
      notificationCount={notificationCount}
    >
      <Outlet />
    </AppShell>
  );
}
