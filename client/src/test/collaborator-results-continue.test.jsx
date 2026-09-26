/**
 * Collaborator shows what a run found and carries it into the next run.
 *
 * 2026-09-26: Collaborator showed each step's status and never its result, so the research a run
 * found was visible only in the database, and the owner carried it into the next goal by hand
 * (a plan cannot pass results between its own steps — FR-46). Two things are pinned here:
 * results render, and "Continue" attaches them to the follow-up goal the owner approves.
 *
 * Also pinned: a run that completes on the first poll still shows its final steps. The poll used
 * to set the run first; that flipped it terminal, the effect tore down, and the steps read that
 * followed was discarded — the only steps carrying results.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AppProviders } from "./utils";
import { FINDINGS_MARKER } from "../utils/runFindings";

const {
  mockCreateAgentRun,
  mockGetAgentRun,
  mockApproveAgentRun,
  mockRejectAgentRun,
  mockGetAgentRunSteps,
} = vi.hoisted(() => ({
  mockCreateAgentRun: vi.fn(),
  mockGetAgentRun: vi.fn(),
  mockApproveAgentRun: vi.fn(),
  mockRejectAgentRun: vi.fn(),
  mockGetAgentRunSteps: vi.fn(),
}));

vi.mock("../api/agent.js", () => ({
  createAgentRun: mockCreateAgentRun,
  getAgentRun: mockGetAgentRun,
  approveAgentRun: mockApproveAgentRun,
  rejectAgentRun: mockRejectAgentRun,
  getAgentRunSteps: mockGetAgentRunSteps,
}));

const RUN_ID = "214ac631-baf9-4e3d-93b2-2856585dcef3";
const GOAL = "Recall what I've recorded about marketing aindy-runtime, then research what's missing.";

const COMPLETED = {
  run_id: RUN_ID,
  goal: GOAL,
  status: "completed",
  steps_total: 3,
  steps_completed: 3,
  plan: { steps: [] },
};

// Result shapes captured from the live run (abridged).
const STEPS = {
  data: [
    {
      step_index: 0, tool_name: "memory.recall", status: "success", description: "Recall",
      result: {
        count: 2,
        nodes: [
          { id: "n1", source: "genesis_lock", content: "Masterplan locked: V1 (posture: Stable)" },
          { id: "n2", source: "system_event:masterplan.pace.propose", content: "execution.started from masterplan.pace.propose" },
        ],
      },
    },
    {
      step_index: 1, tool_name: "research.query", status: "success", description: "Research",
      result: { raw_result: "Stick to the Show HN format. Post Tuesday to Thursday, 7-10am PT." },
    },
    { step_index: 2, tool_name: "memory.write", status: "success", description: "Save", result: { node_id: "x" } },
  ],
};

let Assistant;

beforeAll(async () => {
  Assistant = (await import("../components/app/Assistant.jsx")).default;
});

beforeEach(() => {
  vi.clearAllMocks();
  mockCreateAgentRun.mockResolvedValue({ status: "PENDING_APPROVAL", execution_record: { run_id: RUN_ID } });
  mockGetAgentRun.mockResolvedValue(COMPLETED); // completes on the very first poll
  // A real network round-trip, longer than testing-library's 50 ms act-flush interval, so React
  // commits the terminal render (and runs the effect's cleanup) before this resolves, as a browser
  // would. At 30 ms the steps landed before the commit and the ordering bug stayed hidden.
  mockGetAgentRunSteps.mockImplementation(() => new Promise((resolve) => setTimeout(() => resolve(STEPS), 250)));
});

async function openCompletedRun() {
  render(
    <AppProviders>
      <Assistant />
    </AppProviders>,
  );
  // paste, not type: typing a long goal key by key is seconds of work under a parallel run
  await userEvent.click(await screen.findByRole("textbox"));
  await userEvent.paste(GOAL);
  await userEvent.click(screen.getByRole("button", { name: /^run$/i }));
  await screen.findByText(/Continue from this/i);
}

describe("Collaborator shows results and continues from them", () => {
  it("renders what each step returned, even when the run completes on the first poll", async () => {
    await openCompletedRun();
    expect(await screen.findByText(/Stick to the Show HN format/)).toBeInTheDocument();
    expect(screen.getByText(/Masterplan locked: V1/)).toBeInTheDocument();
    expect(screen.queryByText(/execution\.started from/)).not.toBeInTheDocument();
    expect(screen.getByText(/1 system event hidden/)).toBeInTheDocument();
    expect(screen.getByText(/Saved a note/)).toBeInTheDocument();
  });

  it("attaches the findings to the follow-up goal", async () => {
    await openCompletedRun();
    const boxes = screen.getAllByRole("textbox");
    await userEvent.click(boxes[boxes.length - 1]);
    await userEvent.paste("Create the tasks for the first two weeks");
    await userEvent.click(screen.getByRole("button", { name: /^continue$/i }));
    await waitFor(() => expect(mockCreateAgentRun).toHaveBeenCalledTimes(2));
    const goal = mockCreateAgentRun.mock.calls[1][0].goal;
    expect(goal.startsWith("Create the tasks for the first two weeks")).toBe(true);
    expect(goal).toContain(FINDINGS_MARKER);
    expect(goal).toContain("Stick to the Show HN format");
    expect(goal).toContain("Masterplan locked: V1");
    expect(goal).not.toContain("execution.started from");
  });

  it("sends only the owner's words when findings are unchecked", async () => {
    await openCompletedRun();
    await userEvent.click(screen.getByRole("checkbox", { name: /attach this run/i }));
    const boxes = screen.getAllByRole("textbox");
    await userEvent.click(boxes[boxes.length - 1]);
    await userEvent.paste("Just plan week one");
    await userEvent.click(screen.getByRole("button", { name: /^continue$/i }));
    await waitFor(() => expect(mockCreateAgentRun).toHaveBeenCalledTimes(2));
    expect(mockCreateAgentRun.mock.calls[1][0].goal).toBe("Just plan week one");
  });
});
