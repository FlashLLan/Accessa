import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";

export default function AppLayout() {
  const { pathname } = useLocation();
  const { refreshMe } = useAuth();

  // Keeps /users/me current on every page change, e.g. the number of requests
  // waiting for this user's review (Sidebar "Review" item).
  useEffect(() => {
    refreshMe();
  }, [pathname, refreshMe]);

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        <Topbar />
        <main className="page-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}