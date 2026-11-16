// A refusal from the api, read the way ui-kit hands it over.
//
// ui-kit's ApiError carries the response as `.body`, the RAW TEXT, and `.message` is
// `API Error (<status>): <that text>`. There is no `.data`. Code that read `err.data.detail` never
// found the server's sentence and showed the raw JSON instead (found 2026-11-16 on RippleTrace's
// "Read what it answers" for a piece with no stored text).

export function refusalDetail(err) {
  let raw = err?.data ?? err?.body;
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      raw = null;
    }
  }
  if (!raw || typeof raw !== "object") return null;
  const detail = raw.detail ?? raw;
  return typeof detail === "string" ? { message: detail } : detail;
}

// The server's sentence for this refusal, else `fallback`. Never the raw response text.
export function refusalMessage(err, fallback) {
  const detail = refusalDetail(err);
  if (detail?.message) return detail.message;
  if (err?.status === 408 && err?.message) return err.message;
  return fallback;
}
