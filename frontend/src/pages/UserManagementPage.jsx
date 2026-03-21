import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../hooks/useAuth";
import {
  createUser,
  deactivateUser,
  getRoles,
  getUserDetails,
  getUsers,
  reactivateUser,
  updateUserRole,
} from "../api/users";

function normalizeApiUser(user) {
  return {
    id: user.id,
    full_name: user.full_name,
    email: user.email,
    is_active: user.is_active,
    created_at: user.created_at,
    role: user.role,
  };
}

const ROLE_SORT_ORDER = {
  junior: 1,
  mid: 2,
  senior: 3,
  lead: 4,
  admin: 5,
};

export default function UserManagementPage() {
  const { user: currentUser } = useAuth();

  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [search, setSearch] = useState("");
  const [confirmModal, setConfirmModal] = useState({
  open: false,
  title: "",
  message: "",
  confirmText: "Confirm",
  confirmVariant: "primary",
  onConfirm: null,
});

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [editingUserId, setEditingUserId] = useState(null);
  const [sortBy, setSortBy] = useState("full_name");
  const [sortOrder, setSortOrder] = useState("asc");
  const [statusFilter, setStatusFilter] = useState("all");
  const [detailsUser, setDetailsUser] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  const [createForm, setCreateForm] = useState({
    full_name: "",
    email: "",
    password: "",
    role_id: "",
  });
  const [editForm, setEditForm] = useState({
  role_id: "",
});

function formatDateTime(value) {
  if (!value) return "-";

  const date = new Date(value);
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = date.getFullYear();
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");

  return `${day}/${month}/${year} ${hours}:${minutes}`;
}


  const loadData = async () => {
    setLoading(true);
    setError("");

    try {
      const [usersData, rolesData] = await Promise.all([getUsers(), getRoles()]);
      setUsers(usersData.map(normalizeApiUser));
      setRoles(rolesData);
    } catch (err) {
      console.error("Failed to load user management data", err);
      setError(
        err?.response?.data?.detail ||
          err?.message ||
          "Failed to load users."
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

const filteredUsers = useMemo(() => {
  const term = search.trim().toLowerCase();

  let result = [...users];

  if (term) {
    result = result.filter((user) => {
      return (
        user.full_name.toLowerCase().includes(term) ||
        user.email.toLowerCase().includes(term) ||
        (user.role?.name ?? "").toLowerCase().includes(term)
      );
    });
  }

  if (statusFilter === "active") {
    result = result.filter((user) => user.is_active);
  } else if (statusFilter === "inactive") {
    result = result.filter((user) => !user.is_active);
  }

  result.sort((a, b) => {
    let aValue;
    let bValue;

    switch (sortBy) {
      case "role":
        aValue = ROLE_SORT_ORDER[a.role?.name] ?? 999;
        bValue = ROLE_SORT_ORDER[b.role?.name] ?? 999;
        break;

      case "email":
        aValue = (a.email ?? "").toLowerCase();
        bValue = (b.email ?? "").toLowerCase();
        break;

      case "created_at":
        aValue = a.created_at ? new Date(a.created_at).getTime() : 0;
        bValue = b.created_at ? new Date(b.created_at).getTime() : 0;
        break;

      case "full_name":
      default:
        aValue = (a.full_name ?? "").toLowerCase();
        bValue = (b.full_name ?? "").toLowerCase();
        break;
    }

    if (aValue < bValue) return sortOrder === "asc" ? -1 : 1;
    if (aValue > bValue) return sortOrder === "asc" ? 1 : -1;
    return 0;
  });

  return result;
}, [users, search, sortBy, sortOrder, statusFilter]);

  const handleCreateInputChange = (field, value) => {
    setCreateForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleEditClick = (user) => {
    setEditingUserId(user.id);
    setEditForm({
      role_id: String(user.role?.id ?? ""),
    });
    setError("");
    setSuccess("");
  };

  const handleCancelEdit = () => {
    setEditingUserId(null);
    setEditForm({ role_id: "" });
  };

  const handleCreateUser = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    setSuccess("");

    try {
      await createUser({
        full_name: createForm.full_name,
        email: createForm.email,
        password: createForm.password,
        role_id: Number(createForm.role_id),
      });

      setSuccess("User created successfully.");
      setCreateForm({
        full_name: "",
        email: "",
        password: "",
        role_id: "",
      });
      setShowCreateForm(false);
      await loadData();
    } catch (err) {
      console.error("Failed to create user", err);
      setError(
        err?.response?.data?.detail ||
          err?.message ||
          "Failed to create user."
      );
    } finally {
      setSubmitting(false);
    }
  };

  const openConfirmModal = ({
  title,
  message,
  confirmText = "Confirm",
  confirmVariant = "primary",
  onConfirm,
}) => {
  setConfirmModal({
    open: true,
    title,
    message,
    confirmText,
    confirmVariant,
    onConfirm,
  });
};

const closeConfirmModal = () => {
  setConfirmModal({
    open: false,
    title: "",
    message: "",
    confirmText: "Confirm",
    confirmVariant: "primary",
    onConfirm: null,
  });
};

const handleConfirmAction = async () => {
  if (typeof confirmModal.onConfirm === "function") {
    await confirmModal.onConfirm();
  }
  closeConfirmModal();
};

const handleSaveRole = async (targetUser) => {
  const selectedRole = roles.find(
    (role) => role.id === Number(editForm.role_id)
  );

  const nextRoleName = selectedRole?.name || "selected role";

  openConfirmModal({
    title: "Confirm role change",
    message: `Are you sure you want to change ${targetUser.full_name}'s role from ${targetUser.role?.name} to ${nextRoleName}? This change applies immediately.`,
    confirmText: "Change role",
    confirmVariant: "primary",
    onConfirm: async () => {
      setSubmitting(true);
      setError("");
      setSuccess("");

      try {
        await updateUserRole(targetUser.id, Number(editForm.role_id));
        setSuccess(`Updated role for ${targetUser.full_name}.`);
        setEditingUserId(null);
        await loadData();
      } catch (err) {
        console.error("Failed to update user role", err);
        setError(
          err?.response?.data?.detail ||
            err?.message ||
            "Failed to update role."
        );
      } finally {
        setSubmitting(false);
      }
    },
  });
};

const handleToggleActive = async (targetUser) => {
  const isDisabling = targetUser.is_active;
  const actionLabel = isDisabling ? "disable" : "reactivate";

  openConfirmModal({
    title: isDisabling ? "Confirm deactivation" : "Confirm reactivation",
    message: `Are you sure you want to ${actionLabel} ${targetUser.full_name}'s account?`,
    confirmText: isDisabling ? "Disable account" : "Reactivate account",
    confirmVariant: isDisabling ? "danger" : "primary",
    onConfirm: async () => {
      setSubmitting(true);
      setError("");
      setSuccess("");

      try {
        if (targetUser.is_active) {
          await deactivateUser(targetUser.id);
          setSuccess(`Disabled ${targetUser.full_name}.`);
        } else {
          await reactivateUser(targetUser.id);
          setSuccess(`Reactivated ${targetUser.full_name}.`);
        }

        if (editingUserId === targetUser.id) {
          setEditingUserId(null);
        }

        await loadData();
      } catch (err) {
        console.error("Failed to update active status", err);
        setError(
          err?.response?.data?.detail ||
            err?.message ||
            "Failed to update user status."
        );
      } finally {
        setSubmitting(false);
      }
    },
  });
};

  const isSelf = (targetUser) => currentUser?.id === targetUser.id;

  const getStatusLabel = (targetUser) => {
    return targetUser.is_active ? "Active" : "Inactive";
  };

  const getStatusClass = (targetUser) => {
    return targetUser.is_active
      ? "status-badge status-active"
      : "status-badge status-inactive";
  };

  const handleShowDetails = async (targetUser) => {
  setDetailsLoading(true);
  setError("");
  setSuccess("");

  try {
    const data = await getUserDetails(targetUser.id);
    setDetailsUser(data);
  } catch (err) {
    console.error("Failed to load user details", err);
    setError(
      err?.response?.data?.detail ||
        err?.message ||
        "Failed to load user details."
    );
  } finally {
    setDetailsLoading(false);
  }
};

  return (
      <div className="page-card">
        <div className="page-header-row">
          <div>
            <h2 className="page-title">User Management</h2>
            <p className="page-subtitle">
              Create users, change roles, and manage account access.
            </p>
          </div>

          <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setShowCreateForm((prev) => !prev);
                setError("");
                setSuccess("");
              }}
          >
            {showCreateForm ? "Close" : "Add User"}
          </button>
        </div>

        {error && <div className="auth-error">{error}</div>}
        {success && <div className="success-banner">{success}</div>}

        {showCreateForm && (
            <div className="details-section">
              <h3 className="details-section-title">Create User</h3>

              <form className="request-form" onSubmit={handleCreateUser}>
                <div className="form-row">
                  <div className="form-group">
                    <label htmlFor="full_name">Full name</label>
                    <input
                        id="full_name"
                        type="text"
                        value={createForm.full_name}
                        onChange={(e) =>
                            handleCreateInputChange("full_name", e.target.value)
                        }
                        required
                    />
                  </div>

                  <div className="form-group">
                    <label htmlFor="email">Email</label>
                    <input
                        id="email"
                        type="email"
                        value={createForm.email}
                        onChange={(e) =>
                            handleCreateInputChange("email", e.target.value)
                        }
                        required
                    />
                  </div>
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label htmlFor="password">Password</label>
                    <input
                        id="password"
                        type="password"
                        value={createForm.password}
                        onChange={(e) =>
                            handleCreateInputChange("password", e.target.value)
                        }
                        required
                    />
                  </div>

                  <div className="form-group">
                    <label htmlFor="role_id">Role</label>
                    <select
                        id="role_id"
                        value={createForm.role_id}
                        onChange={(e) =>
                            handleCreateInputChange("role_id", e.target.value)
                        }
                        required
                    >
                      <option value="">Select role</option>
                      {roles.map((role) => (
                          <option key={role.id} value={role.id}>
                            {role.name}
                          </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="page-actions">
                  <button type="submit" className="btn btn-primary" disabled={submitting}>
                    {submitting ? "Creating..." : "Create User"}
                  </button>
                </div>
              </form>
            </div>
        )}

        <div className="toolbar-row">
          <div className="toolbar-search">
            <input
                type="text"
                placeholder="Search by name, email, or role"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="toolbar-stats">
            <span className="request-chip">{filteredUsers.length} visible</span>
          </div>
        </div>

        <div className="toolbar-actions">
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="full_name">Sort by name</option>
            <option value="role">Sort by role</option>
            <option value="email">Sort by email</option>
            <option value="created_at">Sort by creation date</option>
          </select>

          {sortBy !== "status" && (
              <select value={sortOrder} onChange={(e) => setSortOrder(e.target.value)}>
                <option value="asc">Ascending</option>
                <option value="desc">Descending</option>
              </select>
          )}

          <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>

        {detailsLoading && <div className="empty-state">Loading user details...</div>}

        {detailsUser && (
            <div className="details-section">
              <div className="page-header-row">
                <div>
                  <h3 className="details-section-title">User Details</h3>
                  <p className="page-subtitle">
                    Summary for {detailsUser.full_name}
                  </p>
                </div>
                <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setDetailsUser(null)}
                >
                  Close
                </button>
              </div>

              <div className="details-grid">
                <div className="detail-box">
                  <span className="detail-label">Full name</span>
                  <strong>{detailsUser.full_name}</strong>
                </div>

                <div className="detail-box">
                  <span className="detail-label">Email</span>
                  <strong>{detailsUser.email}</strong>
                </div>

                <div className="detail-box">
                  <span className="detail-label">Role</span>
                  <strong>{detailsUser.role?.name}</strong>
                </div>

                <div className="detail-box">
                  <span className="detail-label">Created at</span>
                  <strong>{formatDateTime(detailsUser.created_at)}</strong>
                </div>

                <div className="detail-box">
                <span className="detail-label">Requests created</span>
                  <strong>{detailsUser.stats?.total_requests_created ?? 0}</strong>
                </div>

                <div className="detail-box">
                  <span className="detail-label">Requests approved</span>
                  <strong>{detailsUser.stats?.total_requests_approved ?? 0}</strong>
                </div>

                <div className="detail-box">
                  <span className="detail-label">Requests rejected</span>
                  <strong>{detailsUser.stats?.total_requests_rejected ?? 0}</strong>
                </div>

                <div className="detail-box">
                  <span className="detail-label">Status</span>
                  <strong>{detailsUser.is_active ? "Active" : "Inactive"}</strong>
                </div>
              </div>
            </div>
        )}


        {loading ? (
            <div className="empty-state">Loading users...</div>
        ) : (
            <div className="users-table-wrapper">
              <table className="users-table">
                <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>

                  <th>Status</th>
                  <th className="actions-col">Actions</th>
                </tr>
                </thead>
                <tbody>
                {filteredUsers.map((targetUser) => {
                  const editing = editingUserId === targetUser.id;
                  const self = isSelf(targetUser);

                  return (
                      <tr key={targetUser.id}>
                        <td>
                          <div className="user-cell">
                            <div className="user-avatar">
                              {targetUser.full_name.charAt(0).toUpperCase()}
                            </div>
                            <span>{targetUser.full_name}</span>
                          </div>
                        </td>

                        <td>{targetUser.email}</td>

                        <td>
                          {editing ? (
                              <div className="role-edit-wrap">
                                <select
                                    className="role-edit-select"
                                    value={editForm.role_id}
                                    onChange={(e) => setEditForm({role_id: e.target.value})}
                                    disabled={self || submitting}
                                >
                                  {roles.map((role) => (
                                      <option key={role.id} value={role.id}>
                                        {role.name}
                                      </option>
                                  ))}
                                </select>
                              </div>
                          ) : (
                              <span className="role-pill">{targetUser.role?.name}</span>
                          )}
                        </td>

                        <td>
                      <span className={getStatusClass(targetUser)}>
                        {getStatusLabel(targetUser)}
                      </span>
                        </td>

                        <td className="actions-col">
                          <div className="table-actions">
                            {editing ? (
                                <>
                                  <button
                                      type="button"
                                      className="btn btn-primary btn-sm"
                                      onClick={() => handleSaveRole(targetUser)}
                                      disabled={self || submitting}
                                  >
                                    Save
                                  </button>
                                  <button
                                      type="button"
                                      className="btn btn-secondary btn-sm"
                                      onClick={handleCancelEdit}
                                      disabled={submitting}
                                  >
                                    Cancel
                                  </button>
                                </>
                            ) : (
                                <>
                                  <button
                                      type="button"
                                      className="btn btn-secondary btn-sm"
                                      onClick={() => handleShowDetails(targetUser)}
                                      disabled={submitting}
                                  >
                                    Details
                                  </button>


                                  <button
                                      type="button"
                                      className="btn btn-secondary btn-sm"
                                      onClick={() => handleEditClick(targetUser)}
                                      disabled={submitting}
                                  >
                                    Edit
                                  </button>
                                </>
                            )}

                            <button
                                type="button"
                                className={`btn btn-sm ${
                                    targetUser.is_active ? "btn-danger" : "btn-secondary"
                                }`}
                                onClick={() => handleToggleActive(targetUser)}
                                disabled={self || submitting}
                                title={
                                  self
                                      ? "You cannot change your own active status"
                                      : ""
                                }
                            >
                              {targetUser.is_active ? "Disable" : "Reactivate"}
                            </button>
                          </div>
                        </td>
                      </tr>
                  );
                })}
                </tbody>
              </table>

              {filteredUsers.length === 0 && (
                  <div className="empty-state user-empty-state">
                    No users matched your search.
                  </div>
              )}


            </div>
        )}

              {confirmModal.open && (
        <div className="modal-overlay" onClick={closeConfirmModal}>
          <div
            className="confirm-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="confirm-modal-header">
              <h3>{confirmModal.title}</h3>
            </div>

            <div className="confirm-modal-body">
              <p>{confirmModal.message}</p>
            </div>

            <div className="confirm-modal-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={closeConfirmModal}
                disabled={submitting}
              >
                Cancel
              </button>

              <button
                type="button"
                className={`btn ${
                  confirmModal.confirmVariant === "danger"
                    ? "btn-danger"
                    : "btn-primary"
                }`}
                onClick={handleConfirmAction}
                disabled={submitting}
              >
                {confirmModal.confirmText}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}