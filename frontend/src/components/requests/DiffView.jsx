// Unified diff rendered per file: added lines green, removed lines red (FR-22).
import { parseDiff } from "../../utils/diff";

export default function DiffView({ text }) {
  const files = parseDiff(text);

  return (
    <div className="diff-view">
      {files.map((file, index) => {
        const added = file.lines.filter((l) => l.type === "add").length;
        const removed = file.lines.filter((l) => l.type === "del").length;
        return (
          <div key={`${file.name}-${index}`} className="diff-file">
            {file.name && (
              <div className="diff-file-header">
                <span className="git-monospace">{file.name}</span>
                <span className="diff-file-stats">
                  <span className="diff-stat-add">+{added}</span>{" "}
                  <span className="diff-stat-del">−{removed}</span>
                </span>
              </div>
            )}
            <pre className="diff-lines">
              {file.lines.map((line, n) => (
                <div key={n} className={`diff-line diff-${line.type}`}>
                  {line.text || " "}
                </div>
              ))}
            </pre>
          </div>
        );
      })}
    </div>
  );
}
