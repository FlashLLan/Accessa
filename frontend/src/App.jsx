import { Routes, Route, Navigate } from "react-router-dom";
import { getLastWorkspaceSlug, workspaceLoginPath } from "./utils/storage";
import ProtectedRoute from "./components/common/ProtectedRoute";
import RoleGuard from "./components/common/RoleGuard";
import AppLayout from "./components/layout/AppLayout";

import LoginPage from "./pages/LoginPage";
import FindWorkspacePage from "./pages/FindWorkspacePage";
import SignupPage from "./pages/SignupPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import MfaSetupPage from "./pages/MfaSetupPage";
import DashboardPage from "./pages/DashboardPage";
import RequestsPage from "./pages/RequestsPage";
import RequestDetailsPage from "./pages/RequestDetailsPage";
import CreateRequestPage from "./pages/CreateRequestPage";
import ReviewPage from "./pages/ReviewPage";
import UserManagementPage from "./pages/UserManagementPage";
import AuditLogPage from "./pages/AuditLogPage";
import AccountPage from "./pages/AccountPage";
import NotFoundPage from "./pages/NotFoundPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to={workspaceLoginPath(getLastWorkspaceSlug())} replace />} />
      <Route path="/login" element={<FindWorkspacePage />} />
      <Route path="/w/:slug" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />

      <Route element={<ProtectedRoute />}>
        <Route path="/change-password" element={<ChangePasswordPage />} />
        <Route path="/mfa-setup" element={<MfaSetupPage />} />
        <Route element={<AppLayout />}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/requests" element={<RequestsPage />} />
          <Route path="/requests/new" element={<CreateRequestPage />} />
          <Route path="/requests/:id" element={<RequestDetailsPage />} />

          <Route
            element={<RoleGuard allowedRoles={["admin", "lead", "senior"]} />}
          >
            <Route path="/review" element={<ReviewPage />} />
          </Route>

          <Route element={<RoleGuard allowedRoles={["admin"]} />}>
            <Route path="/admin/users" element={<UserManagementPage />} />
            <Route path="/admin/audit-log" element={<AuditLogPage />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

export default App;