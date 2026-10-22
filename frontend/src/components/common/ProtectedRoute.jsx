import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { getLastWorkspaceSlug, workspaceLoginPath } from "../../utils/storage";

export default function ProtectedRoute() {
  const { isAuthenticated, authLoading, user } = useAuth();
  const location = useLocation();

  if (authLoading) {
    return <div>Loading...</div>;
  }

  if (!isAuthenticated) {
    return <Navigate to={workspaceLoginPath(getLastWorkspaceSlug())} replace />;
  }

  // First login: the admin-set initial password is changed first ...
  if (user?.must_change_password) {
    return location.pathname === "/change-password" ? <Outlet /> : <Navigate to="/change-password" replace />;
  }

  // ... then MFA is set up. Nothing else is reachable without MFA.
  if (!user?.mfa_enabled) {
    return location.pathname === "/mfa-setup" ? <Outlet /> : <Navigate to="/mfa-setup" replace />;
  }
  if (location.pathname === "/mfa-setup") {
    return <Navigate to="/dashboard" replace />;
  }

  return <Outlet />;
}
