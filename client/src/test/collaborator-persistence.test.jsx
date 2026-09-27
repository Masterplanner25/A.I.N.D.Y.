/**
 * Collaborator keeps your run when you leave the page.
 *
 * 2026-09-26: the open run lived only in component state, so leaving the page and coming back
 * showed an empty prompt, including a run still awaiting approval. Nothing was lost server-side;
 * Collaborator just never looked. Now the open run is in the URL (`?run=<id>`), and the empty
 * screen lists recent runs, awaiting-approval first.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AppProviders } from "./utils";

const {
  mockCreateAgentRun,
  mockGetAgentRun,
  mockGetAgentRuns,
  mockApproveAgentRun,
  mockRejectAgentRun,
  mockGetAgentRunSteps,
} = vi.hoisted(() => ({
  mockCreateAgentRun: vi.fn(),
  mockGetAgentRun: vi.fn(),
  mockGetAgentRuns: vi.fn(),
  mockApproveAgentRun: vi.fn(),
  mockRejectAgentRun: vi.fn(),
  mockGetAgentRunSteps: vi.fn(),
}));

vi.mock("../api/agent.js", () => ({
  createAgentRun: mockCreateAgentRun,
  getAgentRun: mockGetAgentRun,
  getAgentRuns: mockGetAgentRuns,
  approveAgentRun: mockApproveAgentRun,
  rejectAgentRun: mockRejectAgentRun,
  getAgentRunSteps: mockGetAgentRunSteps,
}));

const DONE = {
  run_id: "run-done",
  goal: "Research Human-AI collaboration techniques",
  status: "completed",
  created_at: "2026-09-26T17:07:53+00:00",
  steps_total: 1,
  steps_completed: 1,
  plan: { steps: [] },
};
const WAITING = {
  run_id: "run-waiting",
  goal: "Draft the launch post",
  status: "pending_approval",
  created_at: "2026-09-26T10:00:00+00:00",
  plan: { steps: [{ tool: "task.create", description: "Create it", risk_level: "low" }] },
};
const STEPS = [
  {
    step_index: 0, tool_name: "research.query", status: "success", description: "Research",
    result: { raw_result: "Calibrate trust with confidence signals." },
  },
];

let Assistant;

beforeAll(async () => {
  Assistant = (await import("../components/app/Assistant.jsx")).default;
});

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/");
  mockGetAgentRuns.mockResolvedValue([DONE, WAITING]);
  mockGetAgentRun.mockImplementation((id) => Promise.resolve(id === DONE.run_id ? DONE : WAITING));
  mockGetAgentRunSteps.mockResolvedValue(STEPS);
});

function renderAt(url) {
  window.history.replaceState({}, "", url);
  render(
    <AppProviders>
      <Assistant />
    </AppProviders>,
  );
}

describe("Collaborator keeps your run when you leave the page", () => {
  it("reopens the run in the URL, results included, even a finished one", async () => {
    renderAt(`/collaborator?run=${DONE.run_id}`);
    expect(await screen.findByRole("heading", { name: DONE.goal })).toBeInTheDocument();
    // A finished run is never polled; its steps load once so the results show.
    expect(await screen.findByText(/Calibrate trust with confidence signals/)).toBeInTheDocument();
    expect(mockGetAgentRun).toHaveBeenCalledWith(DONE.run_id);
  });

  it("lists recent runs on the empty screen, awaiting-approval first, and opens one", async () => {
    renderAt("/collaborator");
    await screen.findByText(/Recent runs/i);
    const rows = screen.getAllByRole("button").filter((b) => /Draft the launch post|Research Human-AI/.test(b.textContent));
    expect(rows[0].textContent).toMatch(/Draft the launch post/); // awaiting approval, though older
    await userEvent.click(rows[1]);
    expect(await screen.findByRole("heading", { name: DONE.goal })).toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get("run")).toBe(DONE.run_id);
  });

  it("puts a new run in the URL, and New clears it", async () => {
    mockCreateAgentRun.mockResolvedValue({ status: "PENDING_APPROVAL", execution_record: { run_id: "run-new" } });
    mockGetAgentRun.mockResolvedValue({ ...WAITING, run_id: "run-new", goal: "Plan week one" });
    renderAt("/collaborator");
    await userEvent.click(await screen.findByRole("textbox"));
    await userEvent.paste("Plan week one");
    await userEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("run")).toBe("run-new"));
    await userEvent.click(await screen.findByRole("button", { name: /^new$/i }));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("run")).toBeNull());
  });
});
