import { refusalDetail, refusalMessage } from "../lib/apiError.js";

// ui-kit's ApiError: `.body` is the raw response text, `.message` embeds it, and there is no `.data`.
function apiError(status, payload) {
  const body = typeof payload === "string" ? payload : JSON.stringify(payload);
  return Object.assign(new Error(`API Error (${status}): ${body}`), { name: "ApiError", status, body });
}

describe("refusalMessage", () => {
  it("reads the server's sentence out of the raw body", () => {
    const err = apiError(409, { detail: { error: "no_text", message: "This piece has no stored text to read yet." } });
    expect(refusalMessage(err, "fallback")).toBe("This piece has no stored text to read yet.");
    expect(refusalDetail(err).error).toBe("no_text");
  });

  it("takes a plain-string detail", () => {
    expect(refusalMessage(apiError(400, { detail: "Password too short" }), "fallback")).toBe("Password too short");
  });

  it("takes a top-level message beside a detail that has none", () => {
    expect(refusalMessage(apiError(402, { detail: { error: "no_key" }, message: "Add it in Settings." }), "fallback"))
      .toBe("Add it in Settings.");
    expect(refusalMessage(apiError(409, { error: "x", message: "Already decided." }), "fallback")).toBe("Already decided.");
  });

  it("never shows raw response text", () => {
    expect(refusalMessage(apiError(500, "<html>Internal Server Error</html>"), "Could not do it")).toBe("Could not do it");
    expect(refusalMessage(apiError(502, { detail: { error: "upstream" } }), "Could not do it")).toBe("Could not do it");
  });

  it("keeps a timeout's own sentence and accepts the older `.data` shape", () => {
    const timeout = Object.assign(new Error("Request timed out after 30 seconds."), { status: 408, body: null });
    expect(refusalMessage(timeout, "fallback")).toBe("Request timed out after 30 seconds.");
    expect(refusalMessage({ data: { detail: { message: "old shape" } } }, "fallback")).toBe("old shape");
  });
});
