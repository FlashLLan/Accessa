import { useEffect, useMemo, useState } from "react";
import Toast from "../components/common/Toast";
import { extractApiError } from "../utils/apiError";
import { getAuditLogs } from "../api/auditLogs";
import { parseUtcDate } from "../utils/requestPresentation";
import { Link } from "react-router-dom";

// Audit action codes written by the backend today. Filters are built from these
// fixed lists, not from whatever values happen to be in the data.
const ACTION_LABELS = {
  LOGIN_SUCCESS: "Login",
  LOGIN_FAILED: "Failed Login",
  MFA_ENROLLED: "MFA Enrolled",
  MFA_VERIFIED: "MFA Verified",
  MFA_FAILED: "MFA Failed",
  MFA_RESET: "MFA Reset",
  MFA_LOCKED: "MFA Locked",
  WORKSPACE_CREATED: "Workspace Created",
  USER_CREATED: "User Created",
  USER_DEACTIVATED: "User Deactivated",
  USER_REACTIVATED: "User Reactivated",
  ROLE_ASSIGNED: "Role Assigned",
  ROLE_CHANGED: "Role Changed",
  PROFILE_UPDATED: "Profile Updated",
  PASSWORD_CHANGED: "Password Changed",
  REQUEST_CREATED: "Request Created",
  REQUEST_SUBMITTED: "Request Submitted",
  REQUEST_UPDATED: "Request Updated",
  REQUEST_APPROVED: "Request Approved",
  REQUEST_REJECTED: "Request Rejected",
  REQUEST_ESCALATED: "Request Escalated",
  REQUEST_DELEGATED: "Request Delegated",
  REQUEST_APPLIED: "Request Applied",
  COMMENT_CREATED: "Comment Created",
  GIT_CONTEXT_LINKED: "Git Context Linked",
  GIT_CONTEXT_UPDATED: "Git Context Updated",
  AI_REVIEW_GENERATED: "AI Review Generated",
  AUDIT_VIEWED: "Audit Log Viewed",
};

const ACTION_FILTER_OPTIONS = Object.keys(ACTION_LABELS);

const ENTITY_LABELS = {
  user: "User",
  change_request: "Change Request",
  audit_log: "Audit Log",
  workspace: "Workspace",
};

// Workspace is deliberately not offered: every entry already belongs to the
// current workspace.
const ENTITY_FILTER_OPTIONS = ["user", "change_request", "audit_log"];

const ACTION_CATEGORIES = {
  authentication: ["LOGIN_SUCCESS", "LOGIN_FAILED", "MFA_ENROLLED", "MFA_VERIFIED", "MFA_FAILED", "MFA_RESET", "MFA_LOCKED"],
  user_management: ["USER_CREATED", "USER_DEACTIVATED", "USER_REACTIVATED", "ROLE_ASSIGNED", "ROLE_CHANGED", "PROFILE_UPDATED", "PASSWORD_CHANGED"],
  change_requests: ["REQUEST_CREATED", "REQUEST_SUBMITTED", "REQUEST_UPDATED", "REQUEST_APPROVED", "REQUEST_REJECTED", "REQUEST_ESCALATED", "REQUEST_DELEGATED", "REQUEST_APPLIED", "COMMENT_CREATED"],
  git: ["GIT_CONTEXT_LINKED", "GIT_CONTEXT_UPDATED"],
  ai: ["AI_REVIEW_GENERATED"],
  admin: ["AUDIT_VIEWED", "WORKSPACE_CREATED"],
};

function getCategoryForAction(action) {
  for (const [cat, actions] of Object.entries(ACTION_CATEGORIES)) {
    if (actions.includes(action)) return cat;
  }
  return "other";
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = parseUtcDate(value);
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = date.getFullYear();
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const seconds = String(date.getSeconds()).padStart(2, "0");
  return `${day}/${month}/${year} ${hours}:${minutes}:${seconds}`;
}

function ActionBadge({ action }) {
  const category = getCategoryForAction(action);
  const classMap = {
    authentication: "status-badge status-pending",
    user_management: "status-badge status-delegated",
    change_requests: "status-badge status-approved",
    git: "status-badge status-escalated",
    ai: "status-badge status-closed",
    admin: "status-badge status-rejected",
    other: "status-badge",
  };
  return (
    <span className={classMap[category] ?? "status-badge"}>
      {ACTION_LABELS[action] ?? action}
    </span>
  );
}

function formatRole(role) {
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : "—";
}

// Readable reference for the entity; entity ids are never shown as text.
// entity_label is resolved by the API within the current workspace.
function EntityReference({ log }) {
  const label = log.entity_label;
  switch (log.entity_type) {
    case "change_request":
      return log.entity_id != null && label ? (
        <Link to={`/requests/${log.entity_id}`} onClick={(e) => e.stopPropagation()}>
          {label}
        </Link>
      ) : (
        <span>{label ?? "Unknown request"}</span>
      );
    case "user":
      return <span>{label ?? "Unknown user"}</span>;
    case "workspace":
      return <span>Workspace: {label ?? "—"}</span>;
    case "audit_log":
      return <span>Audit log</span>;
    default:
      return <span>{label ?? ENTITY_LABELS[log.entity_type] ?? log.entity_type}</span>;
  }
}

export default function AuditLogPage() {
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState({ message: "", type: "error" });

  const [search, setSearch] = useState("");
  const [actionFilter, setActionFilter] = useState("all");
  const [entityFilter, setEntityFilter] = useState("all");
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await getAuditLogs();
        setLogs(data);
      } catch (err) {
        setToast({
          message: extractApiError(err, "Failed to load audit logs."),
          type: "error",
        });
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return logs.filter((log) => {
      if (actionFilter !== "all" && log.action !== actionFilter) return false;
      if (entityFilter !== "all" && log.entity_type !== entityFilter) return false;
      if (term) {
        const haystack = [
          log.action,
          ACTION_LABELS[log.action] ?? "",
          log.entity_type,
          log.entity_label ?? "",
          log.details ?? "",
          log.user?.full_name ?? "",
          log.user?.email ?? "",
          log.actor_role ?? "",
          log.severity ?? "",
          log.ip_address ?? "",
        ]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(term)) return false;
      }
      return true;
    });
  }, [logs, search, actionFilter, entityFilter]);

  const toggleExpand = (id) => setExpandedId((prev) => (prev === id ? null : id));

  return (
    <div className="page-card">
      <div className="page-header-row">
        <div>
          <h2 className="page-title">Audit Log</h2>
          <p className="page-subtitle">
            Complete record of all significant system actions.
          </p>
        </div>
        <span className="request-chip">{filtered.length} entries</span>
      </div>

      <Toast
        message={toast.message}
        type={toast.type}
        onClose={() => setToast({ message: "", type: "error" })}
      />

      <div className="toolbar-row">
        <div className="toolbar-search">
          <input
            type="text"
            placeholder="Search by user, role, action, entity, details or IP"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className="toolbar-actions">
        <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
          <option value="all">All actions</option>
          {ACTION_FILTER_OPTIONS.map((a) => (
            <option key={a} value={a}>
              {ACTION_LABELS[a]}
            </option>
          ))}
        </select>

        <select value={entityFilter} onChange={(e) => setEntityFilter(e.target.value)}>
          <option value="all">All entity types</option>
          {ENTITY_FILTER_OPTIONS.map((e) => (
            <option key={e} value={e}>
              {ENTITY_LABELS[e]}
            </option>
          ))}
        </select>

        {(search || actionFilter !== "all" || entityFilter !== "all") && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => {
              setSearch("");
              setActionFilter("all");
              setEntityFilter("all");
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      {loading ? (
        <div className="empty-state">Loading audit logs...</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">No audit log entries matched your filters.</div>
      ) : (
        <div className="users-table-wrapper">
          <table className="users-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th style={{ minWidth: 260 }}>User</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((log) => {
                const isExpanded = expandedId === log.id;
                const hasExtra =
                  log.old_value || log.new_value || log.severity || log.ip_address || log.user_agent;
                // Role at the time of the action; the user's current role only for
                // older entries written before actor_role existed.
                const role = log.actor_role || log.user?.role?.name;
                return (
                  <>
                    <tr
                      key={log.id}
                      style={{ cursor: hasExtra ? "pointer" : "default" }}
                      onClick={() => hasExtra && toggleExpand(log.id)}
                    >
                      <td style={{ whiteSpace: "nowrap", fontSize: "0.8rem", color: "var(--text-soft)" }}>
                        {formatDateTime(log.created_at)}
                      </td>

                      <td>
                        <div className="user-cell">
                          <div className="user-avatar" style={{ width: 28, height: 28, fontSize: "0.75rem" }}>
                            {(log.user?.full_name ?? "?").charAt(0).toUpperCase()}
                          </div>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: "0.85rem", fontWeight: 500 }}>
                              {log.user?.full_name ?? "Unknown user"}
                            </div>
                            {/* The e-mail comes from the linked user record in the API
                                response; audit rows never store e-mail addresses. */}
                            {log.user?.email && (
                              <div style={{ marginTop: 3, fontSize: "0.75rem", color: "var(--text-soft)", overflowWrap: "anywhere" }}>
                                {log.user.email}
                              </div>
                            )}
                            <div style={{ marginTop: 3, fontSize: "0.75rem", color: "var(--text-soft)" }}>
                              {formatRole(role)}
                            </div>
                          </div>
                        </div>
                      </td>

                      <td>
                        <ActionBadge action={log.action} />
                      </td>

                      <td style={{ fontSize: "0.85rem" }}>
                        {log.entity_type !== "workspace" && log.entity_type !== "audit_log" && (
                          <div style={{ fontSize: "0.75rem", color: "var(--text-soft)" }}>
                            {ENTITY_LABELS[log.entity_type] ?? log.entity_type}
                          </div>
                        )}
                        <div style={{ fontWeight: 500 }}>
                          <EntityReference log={log} />
                        </div>
                      </td>

                      <td style={{ fontSize: "0.85rem", maxWidth: 360 }}>
                        {log.details ?? "—"}
                        {hasExtra && (
                          <span style={{ marginLeft: 6, fontSize: "0.75rem", color: "var(--text-soft)" }}>
                            {isExpanded ? "▲ less" : "▼ more"}
                          </span>
                        )}
                      </td>
                    </tr>

                    {isExpanded && hasExtra && (
                      <tr key={`${log.id}-extra`} style={{ background: "rgba(139, 92, 246, 0.07)" }}>
                        <td colSpan={5} style={{ padding: "10px 18px", fontSize: "0.8rem", color: "var(--text-soft)" }}>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 24px", marginBottom: 4 }}>
                            {log.severity && (
                              <span>
                                <strong style={{ color: "var(--text)" }}>Severity:</strong> {log.severity}
                              </span>
                            )}
                            <span>
                              <strong style={{ color: "var(--text)" }}>IP address:</strong> {log.ip_address ?? "—"}
                            </span>
                            <span style={{ overflowWrap: "anywhere" }}>
                              <strong style={{ color: "var(--text)" }}>User agent:</strong> {log.user_agent ?? "—"}
                            </span>
                          </div>
                          {log.old_value && (
                            <div style={{ marginBottom: 4 }}>
                              <strong style={{ color: "var(--text)" }}>Previous value:</strong>{" "}
                              <code style={{ background: "rgba(255,255,255,0.08)", color: "var(--text)", padding: "1px 6px", borderRadius: 3 }}>
                                {log.old_value}
                              </code>
                            </div>
                          )}
                          {log.new_value && (
                            <div>
                              <strong style={{ color: "var(--text)" }}>New value:</strong>{" "}
                              <code style={{ background: "rgba(255,255,255,0.08)", color: "var(--text)", padding: "1px 6px", borderRadius: 3 }}>
                                {log.new_value}
                              </code>
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
