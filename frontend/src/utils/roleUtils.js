// Role names are stored in lower case ("junior", "mid", ...); shown capitalised.
export function formatRole(role, fallback = "—") {
  const name = String(role || "").trim();
  return name ? name.charAt(0).toUpperCase() + name.slice(1) : fallback;
}
