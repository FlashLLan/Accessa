import { Routes, Route, Navigate } from "react-router-dom";

import ProtectedRoute from "./components/common/ProtectedRoute";
import RoleGuard from "./components/common/RoleGuard";

import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import RequestsPage from "./pages/RequestsPage";
import RequestDetailsPage from "./pages/RequestDetailsPage";
import CreateRequestPage from "./pages/CreateRequestPage";
import ReviewPage from "./pages/ReviewPage";
import UserManagementPage from "./pages/UserManagementPage";
import NotFoundPage from "./pages/NotFoundPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginPage />} />

      <Route element={<ProtectedRoute />}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/requests" element={<RequestsPage />} />
        <Route path="/requests/new" element={<CreateRequestPage />} />
        <Route path="/requests/:id" element={<RequestDetailsPage />} />
      </Route>

      <Route element={<RoleGuard allowedRoles={["admin", "lead", "senior"]} />}>
        <Route path="/review" element={<ReviewPage />} />
      </Route>

      <Route element={<RoleGuard allowedRoles={["admin"]} />}>
        <Route path="/admin/users" element={<UserManagementPage />} />
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

export default App;