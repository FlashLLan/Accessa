// Remembers the last workspace this browser logged into, so "/" and logout can
// send the user back to that workspace's login page. Convenience only: storage
// may be unavailable (private mode, blocked site data), so every access is guarded.
const LAST_WORKSPACE_KEY = "lastWorkspaceSlug";

export function getLastWorkspaceSlug() {
  try {
    return localStorage.getItem(LAST_WORKSPACE_KEY) || "";
  } catch {
    return "";
  }
}

export function setLastWorkspaceSlug(slug) {
  try {
    if (slug) localStorage.setItem(LAST_WORKSPACE_KEY, slug);
  } catch {
    // ignore
  }
}

export function workspaceLoginPath(slug) {
  return slug ? `/w/${slug}` : "/login";
}
