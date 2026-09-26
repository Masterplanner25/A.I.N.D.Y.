import { describe, expect, it } from "vitest";

import {
  FINDINGS_MARKER,
  MAX_FINDINGS_CHARS,
  buildFindingsDigest,
  composeFollowUpGoal,
  splitGoal,
} from "../utils/runFindings.js";

// Step shapes sampled from live `agent_steps` (2026-09-26, runs 214ac631 / e1c4ec7c).
const RESEARCH = {
  tool_name: "research.query",
  status: "success",
  result: { raw_result: "Market Your AI Tool to Developers\n- Organic Channels: GitHub, Hacker News, Reddit" },
};
const RECALL = {
  tool_name: "memory.recall",
  status: "success",
  result: {
    count: 2,
    nodes: [
      { id: "n1", source: "genesis_lock", content: "Masterplan locked: V1 (posture: Stable)" },
      { id: "n2", source: "system_event:masterplan.pace.propose", content: "execution.started from masterplan.pace.propose" },
    ],
  },
};
const WRITE = { tool_name: "memory.write", status: "success", result: { node_id: "abc" } };
const TASK = { tool_name: "task.create", status: "success", result: { name: "Week 1: Prep GitHub repo", status: "pending", task_id: "33" } };
const FAILED = { tool_name: "research.query", status: "failed", result: { raw_result: "should not appear" } };

describe("buildFindingsDigest", () => {
  it("carries what the run found, labelled by tool", () => {
    const digest = buildFindingsDigest([RESEARCH, RECALL, WRITE, TASK]);
    expect(digest).toContain("[research.query]\nMarket Your AI Tool to Developers");
    expect(digest).toContain("[memory.recall]\n- Masterplan locked: V1");
    expect(digest).toContain("[task.create]\nCreated task: Week 1: Prep GitHub repo");
  });

  it("drops recall telemetry, note-writes and failed steps", () => {
    const digest = buildFindingsDigest([RECALL, WRITE, FAILED]);
    expect(digest).not.toContain("execution.started from");
    expect(digest).not.toContain("memory.write");
    expect(digest).not.toContain("should not appear");
  });

  it("is empty when nothing was found", () => {
    expect(buildFindingsDigest([WRITE])).toBe("");
    expect(buildFindingsDigest(null)).toBe("");
  });

  it("is capped", () => {
    const huge = { ...RESEARCH, result: { raw_result: "x".repeat(MAX_FINDINGS_CHARS * 2) } };
    const digest = buildFindingsDigest([huge]);
    expect(digest.length).toBeLessThanOrEqual(MAX_FINDINGS_CHARS + "\n[truncated]".length);
    expect(digest.endsWith("[truncated]")).toBe(true);
  });
});

describe("composeFollowUpGoal / splitGoal", () => {
  it("round-trips the owner's words out of a goal carrying findings", () => {
    const goal = composeFollowUpGoal("  Create the tasks  ", "[research.query]\nfound things");
    expect(goal).toContain(FINDINGS_MARKER);
    expect(splitGoal(goal)).toEqual({ ask: "Create the tasks", hasFindings: true });
  });

  it("adds nothing when there are no findings", () => {
    expect(composeFollowUpGoal("Create the tasks", "")).toBe("Create the tasks");
    expect(splitGoal("Create the tasks")).toEqual({ ask: "Create the tasks", hasFindings: false });
  });
});
