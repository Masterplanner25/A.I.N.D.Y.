import { beforeEach, describe, expect, it, vi } from "vitest";

import { getFeed, getSocialAnalytics, getProfile } from "../api/social.js";

function makeToken(payload) {
  const encoded = btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  return `header.${encoded}.signature`;
}

function stubEnvelope(data) {
  const fetchSpy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    // The live route stamps `X-AINDY-Envelope: v1`; ui-kit >= 2.1.0 resolves a stamped body to
    // `data` inside `request()` (FR-37). A stub without the header is a bare body, not this route.
    headers: { get: (name) => (name === "X-AINDY-Envelope" ? "v1" : null) },
    text: () =>
      Promise.resolve(
        JSON.stringify({
          status: "SUCCESS",
          data,
          result: data,
          events: [],
          next_action: null,
          trace_id: "t-1",
        })
      ),
  });
  vi.stubGlobal("fetch", fetchSpy);
  return fetchSpy;
}

// Every /apps/social route returns the pipeline envelope. Before the unwrap was added,
// the feed handed that object straight to safeMap (nothing rendered, and no empty state
// either) and the analytics panel read `.overview` off the envelope and showed zeros.
describe("social api unwraps the execution envelope", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
    window.localStorage.setItem("token", makeToken({ sub: "u-1" }));
  });

  it("getFeed returns the post array, not the envelope", async () => {
    stubEnvelope([{ post: { id: "p1" } }]);
    const feed = await getFeed();
    expect(Array.isArray(feed)).toBe(true);
    expect(feed).toHaveLength(1);
    expect(feed[0].post.id).toBe("p1");
  });

  it("getSocialAnalytics exposes overview at the top level", async () => {
    stubEnvelope({ overview: { post_count: 7 }, top_posts: [], trend: [] });
    const analytics = await getSocialAnalytics();
    expect(analytics.overview.post_count).toBe(7);
  });

  it("getProfile returns the profile document", async () => {
    stubEnvelope({ username: "shawn", tagline: "builder" });
    const profile = await getProfile("shawn");
    expect(profile.username).toBe("shawn");
  });
});
