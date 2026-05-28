export function formatEnumLabel(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function getStatusBadgeClass(status) {
  const normalized = String(status || "").toLowerCase();

  switch (normalized) {
    case "draft":
      return "status-badge status-draft";
    case "pending_review":
      return "status-badge status-pending-review";
    case "approved":
      return "status-badge status-approved";
    case "rejected":
      return "status-badge status-rejected";
    case "applied":
      return "status-badge status-approved";
    case "escalated":
      return "status-badge status-escalated";
    case "delegated":
      return "status-badge status-delegated";
    case "cancelled":
    case "closed":
      return "status-badge status-draft";
    default:
      return "status-badge";
  }
}

export function formatDate(value) {
  return new Date(value).toLocaleString();
}

export function getDecisionBadgeClass(decision) {
  const normalized = String(decision || "").toLowerCase();

  switch (normalized) {
    case "approved":
      return "status-badge status-approved";
    case "rejected":
      return "status-badge status-rejected";
    default:
      return "status-badge";
  }
}