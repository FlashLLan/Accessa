import { useEffect, useState } from "react";
import Toast from "../components/common/Toast";
import { getWorkspaceSettings, updateWorkspaceSettings } from "../api/workspace";
import { extractApiError } from "../utils/apiError";

const SCOPE_OPTIONS = [
  {
    value: "changed_files",
    label: "Changed files",
    help: "The AI review reads the pull request's diff and the full content of the changed files.",
  },
  {
    value: "extended",
    label: "Extended",
    help: "Also reads files the changed files import or are imported by, plus top-level config files.",
  },
];

export default function WorkspaceSettingsPage() {
  const [saved, setSaved] = useState(null);
  const [scope, setScope] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [toast, setToast] = useState({ message: "", type: "error" });

  useEffect(() => {
    async function load() {
      try {
        const data = await getWorkspaceSettings();
        setSaved(data);
        setScope(data.ai_review_scope);
      } catch (err) {
        setToast({ message: extractApiError(err, "Failed to load workspace settings."), type: "error" });
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, []);

  async function handleSave(e) {
    e.preventDefault();
    try {
      setIsSaving(true);
      const data = await updateWorkspaceSettings({ ai_review_scope: scope });
      setSaved(data);
      setScope(data.ai_review_scope);
      setToast({ message: "Workspace settings saved.", type: "success" });
    } catch (err) {
      setToast({ message: extractApiError(err, "Failed to save workspace settings."), type: "error" });
    } finally {
      setIsSaving(false);
    }
  }

  const unchanged = !saved || scope === saved.ai_review_scope;

  return (
    <div className="page-card">
      <div className="page-header-row">
        <div>
          <h2 className="page-title">Workspace settings</h2>
          <p className="page-subtitle">Settings that apply to everyone in this workspace.</p>
        </div>
      </div>

      <div className="details-section">
        <h3 className="details-section-title">AI review</h3>

        {isLoading ? (
          <p className="form-hint">Loading…</p>
        ) : saved ? (
          <form onSubmit={handleSave}>
            <div className="form-group" style={{ marginBottom: "16px" }}>
              <label htmlFor="ai_review_scope">AI review scope</label>
              <select
                id="ai_review_scope"
                value={scope}
                onChange={(e) => setScope(e.target.value)}
              >
                {SCOPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              {SCOPE_OPTIONS.map((option) => (
                <span key={option.value} className="form-hint">
                  <strong>{option.label}:</strong> {option.help}
                </span>
              ))}
            </div>
            <div className="page-actions">
              <button type="submit" className="btn btn-primary" disabled={isSaving || unchanged}>
                {isSaving ? "Saving..." : "Save"}
              </button>
            </div>
          </form>
        ) : null}
      </div>

      <Toast
        message={toast.message}
        type={toast.type}
        onClose={() => setToast({ message: "", type: "error" })}
      />
    </div>
  );
}
