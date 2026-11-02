import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Toast from "../components/common/Toast";
import WorkspaceLink from "../components/common/WorkspaceLink";
import { useAuth } from "../hooks/useAuth";
import { extractApiError } from "../utils/apiError";
import {
  createUser,
  deactivateUser,
  getRoles,
  getUserDetails,
  getUsers,
  reactivateUser,
  resetUserMfa,
  updateUserRole,
} from "../api/users";
import { formatDateTime } from "../utils/requestPresentation";
import { formatRole } from "../utils/roleUtils";
import { workspaceSignInUrl } from "../utils/storage";

// A details box with several counts on one line, e.g. "10 approved  2 rejected".
function DetailCounts({ label, counts }) {
  return (
    <div className="detail-box detail-box-counts">
      <span className="detail-label">{label}</span>
      <div className="detail-counts">
        {counts.map(([name, count]) => (
          <span key={name}>
            <strong>{count ?? 0}</strong> {name}
          </span>
        ))}
      </div>
    </div>
  );
}

function normalizeApiUser(user) {
  return {
    id: user.id,
    full_name: user.full_name,
    email: user.email,
    is_active: user.is_active,
    mfa_enabled: Boolean(user.mfa_enabled),
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
  const [toast, setToast] = useState({ message: "", type: "error" });

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [editingUserId, setEditingUserId] = useState(null);
  const [sortBy, setSortBy] = useState("full_name");
  const [sortOrder, setSortOrder] = useState("asc");
  const [statusFilter, setStatusFilter] = useState("all");
  const [detailsUser, setDetailsUser] = useState(null);
  // The details open as an expandable row under the user; if that row is
  // below the visible area, scroll just enough to show it.
  const detailsRef = useRef(null);

  useEffect(() => {
    if (detailsUser) {
      detailsRef.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
    }
  }, [detailsUser]);
  // Id of the user whose details are being fetched.
  const [detailsLoadingId, setDetailsLoadingId] = useState(null);

  const [createForm, setCreateForm] = useState({
    full_name: "",
    email: "",
    password: "",
    role_id: "",
  });
  const [editForm, setEditForm] = useState({
  role_id: "",
});



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
        extractApiError(err, err?.message || "Failed to load users.")
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);


 useEffect(() => {
  if (!confirmModal.open) return;

  const originalOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";

  return () => {
    document.body.style.overflow = originalOverflow;
  };
}, [confirmModal.open]);

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
  };

  const handleCancelEdit = () => {
    setEditingUserId(null);
    setEditForm({ role_id: "" });
  };

  const handleCreateUser = async (e) => {
    e.preventDefault();

    if (createForm.password.length < 8) {
      setToast({ message: "Password must be at least 8 characters.", type: "error" });
      return;
    }

    setSubmitting(true);

    try {
      await createUser({
        full_name: createForm.full_name,
        email: createForm.email,
        password: createForm.password,
        role_id: Number(createForm.role_id),
      });

      const signInUrl = workspaceSignInUrl(currentUser?.workspace?.slug);
      setToast({
        message: signInUrl
          ? `User created. Send them the sign-in link ${signInUrl} together with the initial password.`
          : "User created successfully.",
        type: "success",
      });
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
      setToast({
        message: extractApiError(err, err?.message || "Failed to create user."),
        type: "error",
      });
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
    message: `Are you sure you want to change ${targetUser.full_name}'s role from ${formatRole(targetUser.role?.name)} to ${formatRole(nextRoleName)}? This change applies immediately.`,
    confirmText: "Change role",
    confirmVariant: "primary",
    onConfirm: async () => {
      setSubmitting(true);

      try {
        await updateUserRole(targetUser.id, Number(editForm.role_id));
        setToast({ message: `Updated role for ${targetUser.full_name}.`, type: "success" });
        setEditingUserId(null);
        await loadData();
      } catch (err) {
        console.error("Failed to update user role", err);
        setToast({
          message: extractApiError(err, err?.message || "Failed to update role."),
          type: "error",
        });
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

      try {
        if (targetUser.is_active) {
          await deactivateUser(targetUser.id);
          setToast({ message: `Disabled ${targetUser.full_name}.`, type: "success" });
        } else {
          await reactivateUser(targetUser.id);
          setToast({ message: `Reactivated ${targetUser.full_name}.`, type: "success" });
        }

        if (editingUserId === targetUser.id) {
          setEditingUserId(null);
        }

        await loadData();
      } catch (err) {
        console.error("Failed to update active status", err);
        setToast({
          message: extractApiError(err, err?.message || "Failed to update user status."),
          type: "error",
        });
      } finally {
        setSubmitting(false);
      }
    },
  });
};

const handleResetMfa = (targetUser) => {
  openConfirmModal({
    title: "Reset two-factor authentication",
    message: `Reset MFA for ${targetUser.full_name}? Their authenticator app will stop working for Accessa, and they must set up MFA again at their next login before they can do anything else. Do this only after confirming the person's identity.`,
    confirmText: "Reset MFA",
    confirmVariant: "danger",
    onConfirm: async () => {
      setSubmitting(true);
      try {
        await resetUserMfa(targetUser.id);
        setToast({
          message: `MFA reset for ${targetUser.full_name}. They will set it up again at their next login.`,
          type: "success",
        });
        setDetailsUser((open) => (open?.id === targetUser.id ? { ...open, mfa_enabled: false } : open));
        await loadData();
      } catch (err) {
        console.error("Failed to reset MFA", err);
        setToast({ message: extractApiError(err, "Failed to reset MFA."), type: "error" });
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

  // Details toggles the expandable row under the user: open (fetch), or hide.
  const handleToggleDetails = async (targetUser) => {
  if (detailsUser?.id === targetUser.id) {
    setDetailsUser(null);
    return;
  }
  setDetailsLoadingId(targetUser.id);

  try {
    const data = await getUserDetails(targetUser.id);
    setDetailsUser(data);
  } catch (err) {
    console.error("Failed to load user details", err);
    setToast({
      message: extractApiError(err, err?.message || "Failed to load user details."),
      type: "error",
    });
  } finally {
    setDetailsLoadingId(null);
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
              }}
          >
            {showCreateForm ? "Close" : "Add User"}
          </button>
        </div>

        <WorkspaceLink
          slug={currentUser?.workspace?.slug}
          hint="New users sign in here with the initial password you set; they change it at first sign-in."
        />

        {error && <div className="auth-error">{error}</div>}
        <Toast message={toast.message} type={toast.type} onClose={() => setToast({ message: "", type: "error" })} />

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
                            {formatRole(role.name)}
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

                  const showDetails = detailsUser?.id === targetUser.id;

                  return (
                    <Fragment key={targetUser.id}>
                      <tr className={showDetails ? "user-row-expanded" : undefined}>
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
                                        {formatRole(role.name)}
                                      </option>
                                  ))}
                                </select>
                              </div>
                          ) : (
                              <span className="role-pill">{formatRole(targetUser.role?.name)}</span>
                          )}
                        </td>

                        <td>
                          <div className="user-status-cell">
                            <span className={getStatusClass(targetUser)}>
                              {getStatusLabel(targetUser)}
                            </span>
                            <span className="user-mfa-hint">
                              {targetUser.mfa_enabled ? "MFA enrolled" : "MFA not set up"}
                            </span>
                          </div>
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
                                      onClick={() => handleToggleDetails(targetUser)}
                                      disabled={submitting || detailsLoadingId === targetUser.id}
                                      aria-expanded={showDetails}
                                      aria-controls={`user-details-${targetUser.id}`}
                                  >
                                    {detailsLoadingId === targetUser.id
                                        ? "Loading..."
                                        : showDetails ? "Hide details" : "Details"}
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

                            {!self && (
                                <button
                                    type="button"
                                    className="btn btn-secondary btn-sm"
                                    onClick={() => handleResetMfa(targetUser)}
                                    disabled={submitting || !targetUser.mfa_enabled}
                                    title={targetUser.mfa_enabled ? "" : "This user has not set up MFA yet"}
                                >
                                  Reset MFA
                                </button>
                            )}
                          </div>
                        </td>
                      </tr>

                      {showDetails && (
                        <tr className="user-details-row" id={`user-details-${targetUser.id}`} ref={detailsRef}>
                          <td colSpan={5}>
                            <div className="details-grid">
                              <div className="detail-box">
                                <span className="detail-label">Created at</span>
                                <strong>{formatDateTime(detailsUser.created_at)}</strong>
                              </div>

                              <div className="detail-box">
                                <span className="detail-label">MFA</span>
                                <strong>{detailsUser.mfa_enabled ? "Enrolled" : "Not set up"}</strong>
                              </div>

                              {/* How the user's own requests ended up; drafts are only in the total. */}
                              <DetailCounts
                                  label={`Own requests · ${detailsUser.stats?.total_requests_created ?? 0} created`}
                                  counts={[
                                    ["approved", detailsUser.stats?.own_requests_approved],
                                    ["rejected", detailsUser.stats?.own_requests_rejected],
                                    ["pending", detailsUser.stats?.own_requests_pending],
                                  ]}
                              />

                              {/* Decisions this user made on other people's requests. */}
                              <DetailCounts
                                  label="As reviewer"
                                  counts={[
                                    ["approved", detailsUser.stats?.total_requests_approved],
                                    ["rejected", detailsUser.stats?.total_requests_rejected],
                                  ]}
                              />
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
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

{confirmModal.open &&
  createPortal(
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
    </div>,
    document.body
  )}
    </div>
  );
}