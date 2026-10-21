// Splits a unified diff into files and classifies each line (FR-22).
// Files are recognised by "diff --git a/x b/x" or "--- a/x" / "+++ b/x" headers;
// text without any file header becomes one group without a name.

function stripPrefix(path) {
  return path.replace(/^[ab]\//, "").trim();
}

export function parseDiff(text) {
  const files = [];
  let current = null;

  function start(name) {
    current = { name, lines: [] };
    files.push(current);
  }

  const lines = String(text || "").split("\n");
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const gitHeader = line.match(/^diff --git a\/(.+?) b\/(.+)$/);
    if (gitHeader) {
      start(gitHeader[2]);
      continue;
    }
    // "--- a/x" directly followed by "+++ b/x" starts a file (unless a
    // "diff --git" header already did).
    if (line.startsWith("--- ") && lines[i + 1]?.startsWith("+++ ")) {
      const oldPath = line.slice(4);
      const newPath = lines[i + 1].slice(4);
      const name = newPath.trim() === "/dev/null" ? stripPrefix(oldPath) : stripPrefix(newPath);
      if (!current || current.lines.some((l) => l.type !== "meta")) start(name);
      else current.name = name;
      i += 1;
      continue;
    }
    if (!current) start(null);
    let type = "context";
    if (line.startsWith("@@")) type = "hunk";
    else if (line.startsWith("+")) type = "add";
    else if (line.startsWith("-")) type = "del";
    else if (/^(index |new file mode|deleted file mode|similarity index|rename (from|to) |old mode|new mode|Binary files)/.test(line)) type = "meta";
    current.lines.push({ type, text: line });
  }
  return files.filter((f) => f.name || f.lines.some((l) => l.text.trim() !== ""));
}
