import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { getLastWorkspaceSlug, workspaceLoginPath } from "../../utils/storage";

// Allows the listed roles, or anyone `allowIf(user)` accepts.
export default function RoleGuard({ allowedRoles = [], allowIf }) {
  const { isAuthenticated, user, authLoading } = useAuth();

  if (authLoading) {
    return <div>Loading...</div>;
  }

  if (!isAuthenticated || !user) {
    return <Navigate to={workspaceLoginPath(getLastWorkspaceSlug())} replace />;
  }

  if (!allowedRoles.includes(user.role) && !allowIf?.(user)) {
    return <Navigate to="/dashboard" replace />;
  }

  return <Outlet />;
}