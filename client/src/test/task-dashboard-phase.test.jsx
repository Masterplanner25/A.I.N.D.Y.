import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// A task created for a plan lands on a phase — the plan's current one by default, or the
// one picked here. Until 2026-09-10 every task from this screen was created with
// phase_id = NULL: on the plan, invisible to the strategy layer.

const { mockGetTasks, mockCreateTask, mockListMasterPlans, mockGetStrategyLayer } = vi.hoisted(() => ({
  mockGetTasks: vi.fn(),
  mockCreateTask: vi.fn(),
  mockListMasterPlans: vi.fn(),
  mockGetStrategyLayer: vi.fn(),
}));

vi.mock("../api/tasks.js", () => ({
  getTasks: mockGetTasks,
  createTask: mockCreateTask,
  completeTask: vi.fn(),
  startTask: vi.fn(),
  deleteTask: vi.fn(),
}));

vi.mock("../api/masterplan.js", () => ({
  listMasterPlans: mockListMasterPlans,
  getStrategyLayer: mockGetStrategyLayer,
}));

import TaskDashboard from "../components/app/TaskDashboard";

const PHASES = [
  { id: "p1", ordinal: 1, name: "Foundation Building", status: "pending" },
  { id: "p2", ordinal: 2, name: "Platform Development", status: "pending" },
];

async function fillAndPickPlan() {
  render(<TaskDashboard />);
  await waitFor(() => expect(mockListMasterPlans).toHaveBeenCalled());
  fireEvent.change(screen.getByPlaceholderText(/initialize new directive/i), {
    target: { value: "Draft the ethical AI framework" },
  });
  fireEvent.change(screen.getByPlaceholderText(/e\.g\. 1\.5/i), { target: { value: "4" } });
  fireEvent.change(await screen.findByLabelText(/masterplan/i), { target: { value: "10" } });
  await waitFor(() => expect(mockGetStrategyLayer).toHaveBeenCalledWith("10"));
}

describe("TaskDashboard — phase", () => {
  beforeEach(() => {
    mockGetTasks.mockReset();
    mockCreateTask.mockReset();
    mockListMasterPlans.mockReset();
    mockGetStrategyLayer.mockReset();
    mockGetTasks.mockResolvedValue([]);
    mockCreateTask.mockResolvedValue({});
    mockListMasterPlans.mockResolvedValue({ plans: [{ id: 10, version_label: "V1", is_active: true }] });
    mockGetStrategyLayer.mockResolvedValue({ phases: PHASES });
  });

  it("leaves the phase to the plan by default — no phase_id is sent", async () => {
    await fillAndPickPlan();
    expect(await screen.findByLabelText(/phase/i)).toHaveValue("");

    fireEvent.click(screen.getByRole("button", { name: /add/i }));

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalled());
    const payload = mockCreateTask.mock.calls[0][0];
    expect(payload.masterplan_id).toBe(10);
    expect(payload).not.toHaveProperty("phase_id");
  });

  it("sends the picked phase", async () => {
    await fillAndPickPlan();
    fireEvent.change(await screen.findByLabelText(/phase/i), { target: { value: "p2" } });

    fireEvent.click(screen.getByRole("button", { name: /add/i }));

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalled());
    expect(mockCreateTask.mock.calls[0][0].phase_id).toBe("p2");
  });

  it("shows no phase picker without a plan, or for a plan with no layer", async () => {
    mockGetStrategyLayer.mockResolvedValue({ phases: [] });
    render(<TaskDashboard />);
    await waitFor(() => expect(mockListMasterPlans).toHaveBeenCalled());
    expect(screen.queryByLabelText(/phase/i)).not.toBeInTheDocument();

    fireEvent.change(await screen.findByLabelText(/masterplan/i), { target: { value: "10" } });
    await waitFor(() => expect(mockGetStrategyLayer).toHaveBeenCalled());
    expect(screen.queryByLabelText(/phase/i)).not.toBeInTheDocument();
  });
});
