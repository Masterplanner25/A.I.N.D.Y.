import { beforeEach, describe, expect, it, vi } from "vitest";

import { createAgentRun } from "../api/agent.js";

// ui-kit aborts every request at 30 s and throws ApiError 408. Planning a multi-step goal took
// 36 s on 2026-09-26: the server created the run six seconds after the browser gave up, the
// console reported a failure, and a retry made a duplicate — twice that day. On a 408,
// createAgentRun waits for the run to appear rather than failing (FR-47 is the kit's half).

function makeToken(payload) {
  const encoded = btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  return `header.${encoded}.signature`;
}

const GOAL = "Create the tasks for the first two weeks";
const FAST = { pollMs: 1, maxMs: 200, clockSkewMs: 15000 };

function stubFetch({ post, runs }) {
  const fetchSpy = vi.fn((url, opts) => {
    if (opts?.method === "POST") return post();
    return Promise.resolve({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify({ data: runs() })),
    });
  });
  vi.stubGlobal("fetch", fetchSpy);
  return fetchSpy;
}

const aborted = () => Promise.reject(Object.assign(new Error("aborted"), { name: "AbortError" }));

describe("createAgentRun survives the kit's 30 s timeout", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
    window.localStorage.setItem("token", makeToken({ sub: "u-1" }));
  });

  it("returns the run the server finished planning after the browser gave up", async () => {
    const planned = { run_id: "r-new", goal: GOAL, status: "pending_approval", created_at: new Date().toISOString() };
    stubFetch({ post: aborted, runs: () => [planned] });
    const onStillPlanning = vi.fn();
    const run = await createAgentRun({ goal: GOAL }, { onStillPlanning, recovery: FAST });
    expect(run.run_id).toBe("r-new");
    expect(onStillPlanning).toHaveBeenCalledTimes(1);
  });

  it("does not claim an older run with the same goal, or a newer run with another goal", async () => {
    const older = { run_id: "r-old", goal: GOAL, created_at: new Date(Date.now() - 10 * 60000).toISOString() };
    const other = { run_id: "r-other", goal: "something else", created_at: new Date().toISOString() };
    stubFetch({ post: aborted, runs: () => [other, older] });
    await expect(createAgentRun({ goal: GOAL }, { recovery: FAST })).rejects.toThrow(
      /still running on the server/
    );
  });

  it("rethrows anything that is not the timeout, without polling", async () => {
    const fetchSpy = stubFetch({
      post: () => Promise.resolve({ ok: false, status: 422, text: () => Promise.resolve("bad goal") }),
      runs: () => [],
    });
    await expect(createAgentRun({ goal: GOAL }, { recovery: FAST })).rejects.toMatchObject({ status: 422 });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
