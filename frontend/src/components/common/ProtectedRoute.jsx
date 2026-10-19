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

  // An admin-set initial password must be changed before anything else.
  if (user?.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }

  return <Outlet />;
}
