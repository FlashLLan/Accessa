import { useState } from "react";
import { workspaceSignInUrl } from "../../utils/storage";

// The workspace's sign-in link with a Copy button, for admins to send to new users
// together with their initial password.
export default function WorkspaceLink({ slug, hint }) {
  const [copyState, setCopyState] = useState("");
  const url = workspaceSignInUrl(slug);
  if (!url) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopyState("Copied");
    } catch {
      // Clipboard blocked (e.g. not https): the link can still be selected by hand.
      setCopyState("Copy failed");
    }
  };

  return (
    <div className="workspace-link">
      <span className="detail-label">Workspace sign-in link</span>
      <div className="workspace-address">
        <code>{url}</code>
        <button type="button" className="btn btn-secondary" onClick={handleCopy}>
          {copyState || "Copy"}
        </button>
      </div>
      {hint && <small className="form-hint">{hint}</small>}
    </div>
  );
}
