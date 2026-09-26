import { describe, expect, it, vi } from "vitest";

// Creating a run plans it inline: 36 s measured on 2026-09-26, past ui-kit's default 30 s. The
// timeout fired, the console showed a failure for a run created seconds later, and a retry made a
// duplicate — twice. ui-kit 2.1.1 takes a per-call timeout (FR-47); run creation asks for 90 s.

const { mockAuthRequest } = vi.hoisted(() => ({ mockAuthRequest: vi.fn() }));

vi.mock("../api/_core.js", async (importOriginal) => ({
  ...(await importOriginal()),
  authRequest: mockAuthRequest,
}));

const { createAgentRun, CREATE_RUN_TIMEOUT_MS } = await import("../api/agent.js");

describe("createAgentRun gives planning 90 seconds", () => {
  // No beforeEach touching the spy: with this vitest, a spy reset or cleared in a hook that then
  // rejects fails the test on its own (bisected 2026-09-26). Each test sets its own implementation.

  it("asks the kit for a 90 s timeout on this one call", async () => {
    mockAuthRequest.mockResolvedValue({ run_id: "r-1" });
    await expect(createAgentRun({ goal: "Plan the launch" })).resolves.toEqual({ run_id: "r-1" });
    const [, opts] = mockAuthRequest.mock.lastCall;
    expect(CREATE_RUN_TIMEOUT_MS).toBe(90_000);
    expect(opts.timeoutMs).toBe(90_000);
    expect(JSON.parse(opts.body)).toEqual({ goal: "Plan the launch" });
  });

  it("says the run may still arrive when even 90 s runs out, instead of inviting a duplicate", async () => {
    const timeout = Object.assign(new Error("timed out"), { status: 408 });
    mockAuthRequest.mockImplementation(() => Promise.reject(timeout));
    let caught;
    try {
      await createAgentRun({ goal: "Plan the launch" });
    } catch (e) {
      caught = e;
    }
    expect(caught?.message).toMatch(/may still finish: check the run list before submitting again/);
    expect(caught?.cause).toBe(timeout);
  });

  it("passes any other error through unchanged", async () => {
    const err = Object.assign(new Error("bad goal"), { status: 422 });
    mockAuthRequest.mockImplementation(() => Promise.reject(err));
    let caught;
    try {
      await createAgentRun({ goal: "x" });
    } catch (e) {
      caught = e;
    }
    expect(caught).toBe(err);
  });
});
