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
    default:
      return "status-badge";
  }
}

// Backend timestamps are stored in UTC but serialized without a timezone
// marker (e.g. "2026-06-25T20:43:00"). The browser would otherwise parse that
// as local time. Appending "Z" tells it the value is UTC so it converts to the
// viewer's local timezone for display.
export function parseUtcDate(value) {
  if (!value) return null;
  if (typeof value === "string" && !value.endsWith("Z") && !value.includes("+")) {
    value = value + "Z";
  }
  return new Date(value);
}

const pad = (n) => String(n).padStart(2, "0");

// The one date format of the app: 31/10/2026 16:08 (day/month/year, 24-hour,
// the viewer's local time). Seconds only where they matter (the audit log).
export function formatDateTime(value, { seconds = false } = {}) {
  const date = parseUtcDate(value);
  if (!date || Number.isNaN(date.getTime())) return "—";
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}` + (seconds ? `:${pad(date.getSeconds())}` : "");
  return `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()} ${time}`;
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