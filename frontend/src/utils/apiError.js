/**
 * Extracts a human-readable string from an Axios error.
 *
 * FastAPI returns two shapes for errors:
 *  - string  → plain HTTPException detail
 *  - array   → Pydantic 422 validation errors: [{loc, msg, type}, ...]
 *
 * In both cases we want a single string so Toast never receives a non-string.
 */
export function extractApiError(err, fallback = "An unexpected error occurred.") {
  const detail = err?.response?.data?.detail;

  if (!detail) return fallback;

  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const seen = new Set();
    const messages = [];
    for (const e of detail) {
      const msg = typeof e === "string" ? e : (e.msg ?? JSON.stringify(e));
      const clean = msg.replace(/^Value error,\s*/i, "");
      if (!seen.has(clean)) {
        seen.add(clean);
        messages.push(clean);
      }
    }
    return messages.join(" | ");
  }

  return fallback;
}
