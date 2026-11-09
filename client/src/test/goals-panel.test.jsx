import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// GOALS_LAYER_SPEC §6: proposals from the plan, confirmed with the objectives ticked; a goal shows how it is measured
// and its progress, or "no measurement yet" / "declared"; a declared goal is marked done by the person. Never a score.

afterEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.doUnmock("../api/goals.js");
});

const OBJECTIVES = [{ id: "o1", name: "Ethical AI Framework" }, { id: "o2", name: "Platform Enablement" }];

async function renderPanel(api) {
  vi.doMock("../api/goals.js", () => ({
    confirmGoal: vi.fn().mockResolvedValue({}),
    dropGoal: vi.fn().mockResolvedValue({}),
    updateGoal: vi.fn().mockResolvedValue({}),
    createGoal: vi.fn().mockResolvedValue({}),
    ...api,
  }));
  const { default: GoalsPanel } = await import("../components/app/GoalsPanel.jsx");
  render(<GoalsPanel />);
}

describe("GoalsPanel", () => {
  it("confirms a proposal with the objectives ticked, and drops another", async () => {
    const getGoalsOverview = vi.fn().mockResolvedValue({
      proposed: [
        { id: "g1", name: "Successful deployment of enabling platforms", source: "success_criterion",
          measure: "objectives", objectives: [{ id: "o2", name: "Platform Enablement" }], status: "proposed" },
        { id: "g2", name: "Positive feedback from users and stakeholders", source: "success_criterion",
          measure: "declared", objectives: [], status: "proposed" },
      ],
      goals: [],
      objectives: OBJECTIVES,
    });
    const confirmGoal = vi.fn().mockResolvedValue({});
    const dropGoal = vi.fn().mockResolvedValue({});
    await renderPanel({ getGoalsOverview, confirmGoal, dropGoal });

    const proposals = await screen.findAllByTestId("goal-proposal");
    expect(proposals[0]).toHaveTextContent("measured through the objectives ticked");
    expect(proposals[1]).toHaveTextContent("declared: no number, you mark it done");
    fireEvent.click(proposals[0].querySelectorAll("input[type=checkbox]")[0]); // tick Ethical AI Framework too
    fireEvent.click(proposals[0].querySelector("button"));
    await waitFor(() => expect(confirmGoal).toHaveBeenCalledWith("g1", { objective_ids: ["o2", "o1"] }));
    fireEvent.click(screen.getAllByRole("button", { name: "Drop" })[1]);
    await waitFor(() => expect(dropGoal).toHaveBeenCalledWith("g2"));
  });

  it("shows each goal's measure and progress, never a made-up number, and marks a declared one done", async () => {
    const getGoalsOverview = vi.fn().mockResolvedValue({
      proposed: [],
      goals: [
        { id: "a", name: "Financial Freedom", source: "anchor", measure: "anchor", progress: null, status: "active",
          target_value: 1000000, unit: "USD", target_date: "2030-12-31T00:00:00+00:00", objectives: [] },
        { id: "b", name: "Formation of strategic partnerships", source: "success_criterion", measure: "objectives",
          progress: 0.4, status: "active", objectives: [{ id: "o3", name: "Partnership Development" }] },
        { id: "c", name: "Sustainable funding models in place", source: "success_criterion", measure: "declared",
          progress: null, status: "active", objectives: [] },
      ],
      objectives: OBJECTIVES,
    });
    const updateGoal = vi.fn().mockResolvedValue({});
    await renderPanel({ getGoalsOverview, updateGoal });

    const goals = await screen.findAllByTestId("goal");
    expect(goals[0]).toHaveTextContent("no measurement yet");
    expect(goals[0]).toHaveTextContent("anchor: 1,000,000 USD by 2030-12-31");
    expect(goals[1]).toHaveTextContent("40% attained");
    expect(goals[1]).toHaveTextContent("through Partnership Development");
    expect(goals[2]).toHaveTextContent("declared: you mark it done");
    expect(goals[0].textContent).not.toMatch(/0% attained/);
    expect(screen.getByTestId("goals-panel").textContent).not.toMatch(/score/i);

    // Mark done on the declared goal and on the objectives one, never on the anchor (owner, 2026-11-09).
    expect(goals[0].querySelector("button")?.textContent).not.toBe("Mark done");
    const markDone = screen.getAllByRole("button", { name: "Mark done" });
    expect(markDone).toHaveLength(2);
    fireEvent.click(markDone[1]);
    await waitFor(() => expect(updateGoal).toHaveBeenCalledWith("c", { status: "completed" }));
  });

  it("adds a goal of your own", async () => {
    const getGoalsOverview = vi.fn().mockResolvedValue({ proposed: [], goals: [], objectives: OBJECTIVES });
    const createGoal = vi.fn().mockResolvedValue({});
    await renderPanel({ getGoalsOverview, createGoal });

    fireEvent.change(await screen.findByLabelText("New goal"), { target: { value: "Ship the runtime" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(createGoal).toHaveBeenCalledWith({ name: "Ship the runtime", objectiveIds: [] }));
  });

  it("reads an objectives goal at 100% as all planned work done", async () => {
    const getGoalsOverview = vi.fn().mockResolvedValue({
      proposed: [],
      goals: [{ id: "p", name: "Formation of strategic partnerships", source: "success_criterion", measure: "objectives",
                progress: 1, status: "active", objectives: [{ id: "o3", name: "Partnership Development" }] }],
      objectives: OBJECTIVES,
    });
    await renderPanel({ getGoalsOverview });
    expect(await screen.findByTestId("goal")).toHaveTextContent("all planned work done");
  });
});
