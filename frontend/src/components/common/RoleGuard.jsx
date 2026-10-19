import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { getLastWorkspaceSlug, workspaceLoginPath } from "../../utils/storage";

export default function RoleGuard({ allowedRoles = [] }) {
  const { isAuthenticated, user, authLoading } = useAuth();

  if (authLoading) {
    return <div>Loading...</div>;
  }

  if (!isAuthenticated || !user) {
    return <Navigate to={workspaceLoginPath(getLastWorkspaceSlug())} replace />;
  }

  if (!allowedRoles.includes(user.role)) {
    return <Navigate to="/dashboard" replace />;
  }

  return <Outlet />;
}