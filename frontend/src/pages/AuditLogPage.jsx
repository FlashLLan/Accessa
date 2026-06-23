import { useEffect, useMemo, useState } from "react";
import Toast from "../components/common/Toast";
import { extractApiError } from "../utils/apiError";
import { getAuditLogs } from "../api/auditLogs";

const ACTION_LABELS = {
  login: "Login",
  failed_login: "Failed Login",
  register: "Register",
  create_user: "Create User",
  deactivate_user: "Deactivate User",
  reactivate_user: "Reactivate User",
  update_user_role: "Update Role",
  profile_updated: "Profile Updated",
  password_changed: "Password Changed",
  create_change_request: "Create Request",
  submit_change_request: "Submit Request",
  update_change_request: "Update Request",
  approve_change_request: "Approve Request",
  reject_change_request: "Reject Request",
  escalate_change_request: "Escalate Request",
  delegate_change_request: "Delegate Request",
  apply_change_request: "Apply Request",
  add_comment: "Add Comment",
  git_context_linked: "Git Context Linked",
  trigger_ai_review: "AI Review Triggered",
};

const ENTITY_LABELS = {
  user: "User",
  change_request: "Change Request",
  git_context: "Git Context",
  ai_review: "AI Review",
};

const ACTION_CATEGORIES = {
  authentication: ["login", "failed_login", "register"],
  user_management: ["create_user", "deactivate_user", "reactivate_user", "update_user_role", "profile_updated", "password_changed"],
  change_requests: ["create_change_request", "submit_change_request", "update_change_request", "approve_change_request", "reject_change_request", "escalate_change_request", "delegate_change_request", "apply_change_request", "add_comment"],
  git: ["git_context_linked"],
  ai: ["trigger_ai_review"],
};

function getCategoryForAction(action) {
  for (const [cat, actions] of Object.entries(ACTION_CATEGORIES)) {
    if (actions.includes(action)) return cat;
  }
  return "other";
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
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
    other: "status-badge",
  };
  return (
    <span className={classMap[category] ?? "status-badge"}>
      {ACTION_LABELS[action] ?? action}
    </span>
  );
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

  const uniqueActions = useMemo(
    () => [...new Set(logs.map((l) => l.action))].sort(),
    [logs]
  );

  const uniqueEntities = useMemo(
    () => [...new Set(logs.map((l) => l.entity_type))].sort(),
    [logs]
  );

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return logs.filter((log) => {
      if (actionFilter !== "all" && log.action !== actionFilter) return false;
      if (entityFilter !== "all" && log.entity_type !== entityFilter) return false;
      if (term) {
        const haystack = [
          log.action,
          log.entity_type,
          String(log.entity_id),
          log.details ?? "",
          log.user?.full_name ?? "",
          log.user?.email ?? "",
          log.severity ?? "",
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
            placeholder="Search by user, action, entity, or details"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className="toolbar-actions">
        <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
          <option value="all">All actions</option>
          {uniqueActions.map((a) => (
            <option key={a} value={a}>
              {ACTION_LABELS[a] ?? a}
            </option>
          ))}
        </select>

        <select value={entityFilter} onChange={(e) => setEntityFilter(e.target.value)}>
          <option value="all">All entity types</option>
          {uniqueEntities.map((e) => (
            <option key={e} value={e}>
              {ENTITY_LABELS[e] ?? e}
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
                <th>User</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((log) => {
                const isExpanded = expandedId === log.id;
                const hasExtra = log.old_value || log.new_value || log.severity;
                return (
                  <>
                    <tr
                      key={log.id}
                      style={{ cursor: hasExtra ? "pointer" : "default" }}
                      onClick={() => hasExtra && toggleExpand(log.id)}
                    >
                      <td style={{ whiteSpace: "nowrap", fontSize: "0.8rem", color: "var(--text-muted)" }}>
                        {formatDateTime(log.created_at)}
                      </td>

                      <td>
                        <div className="user-cell">
                          <div className="user-avatar" style={{ width: 28, height: 28, fontSize: "0.75rem" }}>
                            {(log.user?.full_name ?? "?").charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <div style={{ fontSize: "0.85rem", fontWeight: 500 }}>
                              {log.user?.full_name ?? "—"}
                            </div>
                            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                              {log.user?.email ?? ""}
                            </div>
                          </div>
                        </div>
                      </td>

                      <td>
                        <ActionBadge action={log.action} />
                      </td>

                      <td style={{ fontSize: "0.85rem" }}>
                        <span style={{ fontWeight: 500 }}>
                          {ENTITY_LABELS[log.entity_type] ?? log.entity_type}
                        </span>
                        <span style={{ color: "var(--text-muted)", marginLeft: 4 }}>
                          #{log.entity_id}
                        </span>
                      </td>

                      <td style={{ fontSize: "0.85rem", maxWidth: 360 }}>
                        {log.details ?? "—"}
                        {hasExtra && (
                          <span style={{ marginLeft: 6, fontSize: "0.75rem", color: "var(--text-muted)" }}>
                            {isExpanded ? "▲ less" : "▼ more"}
                          </span>
                        )}
                      </td>
                    </tr>

                    {isExpanded && hasExtra && (
                      <tr key={`${log.id}-extra`} style={{ background: "rgba(139, 92, 246, 0.07)" }}>
                        <td colSpan={5} style={{ padding: "10px 18px", fontSize: "0.8rem", color: "var(--text-soft)" }}>
                          {log.severity && (
                            <div style={{ marginBottom: 4 }}>
                              <strong style={{ color: "var(--text)" }}>Severity:</strong> {log.severity}
                            </div>
                          )}
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
