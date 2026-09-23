import { beforeEach, describe, expect, it, vi } from "vitest";

import { getIdentityProfile, getIdentityEvolution } from "../api/identity.js";
import { getMemoryNodes } from "../api/memory.js";

function makeToken(payload) {
  const encoded = btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  return `header.${encoded}.signature`;
}

function stubResponse(body, { stamped = true } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      // The live route stamps `X-AINDY-Envelope: v1`; ui-kit >= 2.1.0 resolves a stamped body to
      // `data` inside `request()` (FR-37). A stub without the header is a bare body, not this route.
      headers: { get: (name) => (stamped && name === "X-AINDY-Envelope" ? "v1" : null) },
      text: () => Promise.resolve(JSON.stringify(body)),
    })
  );
}

describe("identity api unwraps the execution envelope", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
    window.localStorage.setItem("token", makeToken({ sub: "u-1" }));
  });

  // IdentityDashboard reads profile?.communication / .tools / .decision_making /
  // .learning. Off the envelope those are all undefined and every card renders blank.
  it("getIdentityProfile returns the dimension payload", async () => {
    stubResponse({
      status: "success",
      data: {
        communication: { tone: "direct" },
        tools: { preferred_languages: ["python"] },
        decision_making: { risk_tolerance: "high" },
        learning: { style: "hands-on" },
        evolution: { observation_count: 4, change_count: 2 },
      },
      trace_id: "t-1",
    });
    const profile = await getIdentityProfile();
    expect(profile.communication.tone).toBe("direct");
    expect(profile.evolution.observation_count).toBe(4);
  });

  it("getIdentityEvolution returns the evolution payload", async () => {
    stubResponse({ status: "success", data: { total_changes: 3, history: [] } });
    const evo = await getIdentityEvolution();
    expect(evo.total_changes).toBe(3);
  });
});

describe("memory api leaves unenveloped responses alone", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
    window.localStorage.setItem("token", makeToken({ sub: "u-1" }));
  });

  // /apps/memory returns {nodes, execution_envelope} directly — no {status, data}
  // wrapper — so memory.js must NOT unwrap. This pins that difference.
  it("getMemoryNodes returns the raw payload with nodes at the top level", async () => {
    // /apps/memory answers through raw_json_adapter: a bare body, never stamped.
    stubResponse({ nodes: [{ id: "n1", content: "User account created" }], execution_envelope: {} }, { stamped: false });
    const res = await getMemoryNodes();
    expect(res.nodes).toHaveLength(1);
    expect(res.nodes[0].content).toBe("User account created");
  });
});
