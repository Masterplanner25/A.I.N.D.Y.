/**
 * The Assistant agent face must handle every shape the agent surface returns.
 *
 * Reported: an agent run "seems stuck when planning". The backend was fine — the Claude
 * planner produced a plan (PENDING_APPROVAL) in ~12s. But the create response wraps the run
 * in an execution envelope: run_id lives under execution_record, the plan under result.plan,
 * and the status is UPPERCASE — while the component only read the flat GET-shape (run.run_id,
 * run.plan). So after a create, runId was undefined: the poll never started, the plan never
 * rendered, and Approve did nothing. It looked stuck at "planning".
 *
 * These tests pin the create/approve envelope shape and the { data: [...] } steps shape,
 * captured from live responses.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AppProviders } from "./utils";

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
  // The empty screen lists recent runs; these tests start from a fresh one.
  getAgentRuns: () => Promise.resolve([]),
  approveAgentRun: mockApproveAgentRun,
  rejectAgentRun: mockRejectAgentRun,
  getAgentRunSteps: mockGetAgentRunSteps,
}));

const RUN_ID = "88ea0a19-a8f2-4743-ba3f-61a574b09831";

// Live CREATE / APPROVE shape: envelope. run_id under execution_record, plan under result.plan.
const ENVELOPE_PENDING = {
  status: "PENDING_APPROVAL",
  execution_record: { run_id: RUN_ID },
  result: {
    objective: "Pick a framework.",
    plan: {
      steps: [
        { tool: "memory.recall", description: "Recall prior context.", risk_level: "low" },
        { tool: "research.query", description: "Compare frameworks.", risk_level: "low" },
      ],
    },
  },
  trace_id: "t1",
};

// Live GET /runs/{id} shape: flat detail row.
const DETAIL_PENDING = {
  run_id: RUN_ID,
  status: "pending_approval",
  plan: { steps: ENVELOPE_PENDING.result.plan.steps },
};

let Assistant;

beforeAll(async () => {
  Assistant = (await import("../components/app/Assistant.jsx")).default;
});

beforeEach(() => {
  vi.clearAllMocks();
  // Collaborator keeps the open run in `?run=`; the router uses real history, so reset it or one
  // test's run reopens in the next.
  window.history.replaceState({}, "", "/");
  mockGetAgentRun.mockResolvedValue(DETAIL_PENDING);
  mockGetAgentRunSteps.mockResolvedValue({ data: [] }); // steps come back wrapped, not bare
});

async function startRun() {
  render(
    <AppProviders>
      <Assistant />
    </AppProviders>,
  );
  const input = await screen.findByRole("textbox");
  await userEvent.type(input, "Pick an agent framework.");
  const submit = screen.getByRole("button", { name: /run|start|send|go/i });
  await userEvent.click(submit);
}

describe("Assistant handles the agent envelope shape", () => {
  it("renders the plan from a create (envelope) response, not just the flat GET shape", async () => {
    mockCreateAgentRun.mockResolvedValue(ENVELOPE_PENDING);
    await startRun();
    // Plan steps live at result.plan.steps on the create response — must still render.
    await waitFor(() => expect(screen.getByText(/research\.query/i)).toBeInTheDocument());
  });

  it("derives run_id from execution_record so the poll starts", async () => {
    mockCreateAgentRun.mockResolvedValue(ENVELOPE_PENDING);
    await startRun();
    // The poll uses runId; if it were undefined (the bug) getAgentRun is never called.
    await waitFor(() => expect(mockGetAgentRun).toHaveBeenCalledWith(RUN_ID));
  });

  it("keeps Approve wired when the create response has no top-level run_id", async () => {
    mockCreateAgentRun.mockResolvedValue(ENVELOPE_PENDING);
    mockApproveAgentRun.mockResolvedValue({
      status: "APPROVED",
      execution_record: { run_id: RUN_ID },
      result: ENVELOPE_PENDING.result,
    });
    await startRun();
    const approve = await screen.findByRole("button", { name: /approve/i });
    await userEvent.click(approve);
    await waitFor(() => expect(mockApproveAgentRun).toHaveBeenCalledWith(RUN_ID));
  });
});
