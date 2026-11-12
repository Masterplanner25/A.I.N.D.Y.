import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// What to ask the agent (owner, 2026-11-11): starting points its tools do well, the first one about the person's top
// goal, each filling the box rather than running.

afterEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.doUnmock("../api/goals.js");
});

async function renderCard(listActiveGoals) {
  vi.doMock("../api/goals.js", () => ({ listActiveGoals }));
  const { default: AgentStartingPoints } = await import("../components/app/AgentStartingPoints.jsx");
  const onPick = vi.fn();
  render(<AgentStartingPoints onPick={onPick} />);
  return onPick;
}

describe("AgentStartingPoints", () => {
  it("names the top goal in the first starting point, and fills the box without running", async () => {
    const onPick = await renderCard(vi.fn().mockResolvedValue({
      data: [{ name: "Formation of strategic partnerships", priority: 0.9 }, { name: "Other", priority: 0.5 }],
    }));
    const first = await screen.findByRole("button", { name: /Turn a goal into this week's work/ });
    fireEvent.click(first);
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(expect.stringContaining(
      'For my goal "Formation of strategic partnerships", create the three most useful next tasks',
    )));
  });

  it("reads the flow's result key too", async () => {
    const onPick = await renderCard(vi.fn().mockResolvedValue({ goals_list_result: [{ name: "Ship Nodus" }] }));
    await waitFor(() => {
      fireEvent.click(screen.getByRole("button", { name: /Turn a goal into this week's work/ }));
      expect(onPick).toHaveBeenLastCalledWith(expect.stringContaining('my goal "Ship Nodus"'));
    });
  });

  it("still offers every starting point with no goals, or when the read fails", async () => {
    const onPick = await renderCard(vi.fn().mockRejectedValue(new Error("offline")));
    const card = screen.getByTestId("agent-starting-points");
    expect(card).toHaveTextContent("What to ask");
    expect(screen.getAllByRole("button")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: /Turn a goal into this week's work/ }));
    expect(onPick).toHaveBeenCalledWith(expect.stringContaining("what my plan says matters most right now"));
    fireEvent.click(screen.getByRole("button", { name: /Research that stays/ }));
    expect(onPick).toHaveBeenLastCalledWith("Research [topic], then save the findings to my memory tagged [tag].");
  });

  it("names only tools the agent has", async () => {
    const { startingPoints } = await import("../utils/agentStartingPoints.js");
    const known = new Set([
      "memory.recall", "memory.write", "reasoning.evaluate", "arm.analyze", "arm.generate", "arm.autotune",
      "freelance.optimize_pricing", "freelance.performance", "genesis.message", "market.propose", "content.draft",
      "search.query", "leadgen.search", "research.query", "leadgen.act", "task.create", "task.complete",
    ]);
    for (const point of startingPoints(null)) {
      for (const tool of point.uses.split(" · ")) expect(known.has(tool)).toBe(true);
    }
  });
});
