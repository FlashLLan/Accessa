const GITHUB_PR_URL = /https?:\/\/(?:www\.)?github\.com\/([\w.-]+)\/([\w.-]+?)\/pull\/(\d+)[^\s;,)]*/gi;
const GITHUB_REPO_URL = /https?:\/\/(?:www\.)?github\.com\/([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?(?=[\s;,)]|$)/gi;
const COMMIT_HASH = /\b[0-9a-f]{12,64}\b/gi;

// Short form for the collapsed row: GitHub PR URLs as owner/repo#123, repository
// URLs as owner/repo, commit hashes as their first 7 characters. The full text
// is in the expanded row.
export function summarizeDetails(text) {
  if (!text) return text;
  return text
    .replace(GITHUB_PR_URL, (_, owner, repo, number) => `${owner}/${repo}#${number}`)
    .replace(GITHUB_REPO_URL, (_, owner, repo) => `${owner}/${repo}`)
    .replace(COMMIT_HASH, (hash) => hash.slice(0, 7));
}
