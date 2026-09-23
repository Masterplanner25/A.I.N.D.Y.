import { beforeEach, describe, expect, it, vi } from "vitest";

import { getTasks } from "../api/tasks.js";

function makeToken(payload) {
  const encoded = btoa(JSON.stringify(payload)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  return `header.${encoded}.signature`;
}

function stubResponse(body) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      // The live route stamps `X-AINDY-Envelope: v1`; ui-kit >= 2.1.0 resolves a stamped body to
      // `data` inside `request()` (FR-37). A stub without the header is a bare body, not this route.
      headers: { get: (name) => (name === "X-AINDY-Envelope" ? "v1" : null) },
      text: () => Promise.resolve(JSON.stringify(body)),
    })
  );
}

// `/apps/tasks/list` returns {status, data: {tasks: [...], execution_envelope: {...}}}.
// Unwrapping the envelope alone leaves an object, and TaskDashboard's
// `Array.isArray(data) ? [...data] : []` then discards every task.
describe("getTasks flattens the nested list payload", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
    window.localStorage.setItem("token", makeToken({ sub: "u-1" }));
  });

  it("returns the task array from data.tasks", async () => {
    stubResponse({
      status: "success",
      data: {
        tasks: [{ task_id: 2, task_name: "Walkthrough directive", status: "pending" }],
        execution_envelope: { status: "SUCCESS" },
      },
    });
    const tasks = await getTasks();
    expect(Array.isArray(tasks)).toBe(true);
    expect(tasks).toHaveLength(1);
    expect(tasks[0].task_name).toBe("Walkthrough directive");
  });

  it("passes a bare array through unchanged", async () => {
    stubResponse({ status: "success", data: [{ task_id: 1, task_name: "direct" }] });
    const tasks = await getTasks();
    expect(tasks).toHaveLength(1);
    expect(tasks[0].task_name).toBe("direct");
  });

  it("yields an empty array when the payload has no tasks", async () => {
    stubResponse({ status: "success", data: { execution_envelope: { status: "SUCCESS" } } });
    await expect(getTasks()).resolves.toEqual([]);
  });
});
