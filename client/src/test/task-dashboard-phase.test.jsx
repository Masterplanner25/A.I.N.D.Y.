import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// A task created for a plan lands on a phase — the plan's current one by default, or the
// one picked here. Until 2026-09-10 every task from this screen was created with
// phase_id = NULL: on the plan, invisible to the strategy layer.

const { mockGetTasks, mockCreateTask, mockListMasterPlans, mockGetStrategyLayer, mockPromote } = vi.hoisted(() => ({
  mockGetTasks: vi.fn(),
  mockCreateTask: vi.fn(),
  mockListMasterPlans: vi.fn(),
  mockGetStrategyLayer: vi.fn(),
  mockPromote: vi.fn(),
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
  promoteTaskToStrategy: mockPromote,
}));

import TaskDashboard from "../components/app/TaskDashboard";

const PHASES = [
  { id: "p1", ordinal: 1, name: "Foundation Building", status: "pending" },
  { id: "p2", ordinal: 2, name: "Platform Development", status: "pending" },
];
const STRATEGIES = [
  { id: "s1", phase_id: "p1", name: "Establish Authority", status: "active" },
  { id: "s2", phase_id: "p1", name: "Guest posts", status: "abandoned" },
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
    mockPromote.mockReset();
    mockGetStrategyLayer.mockResolvedValue({ phases: PHASES, strategies: STRATEGIES });
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

  it("offers only open strategies, and sends the picked one", async () => {
    await fillAndPickPlan();
    const picker = await screen.findByLabelText(/strategy/i);
    expect(picker).toHaveTextContent("Establish Authority");
    expect(picker).not.toHaveTextContent("Guest posts");
    fireEvent.change(picker, { target: { value: "s1" } });

    fireEvent.click(screen.getByRole("button", { name: /add/i }));

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalled());
    expect(mockCreateTask.mock.calls[0][0].strategy_id).toBe("s1");
  });

  it("promotes a plan task to a strategy, after confirming", async () => {
    mockGetTasks.mockResolvedValue([
      { task_id: 20, task_name: "Establish Authority", status: "in_progress", time_spent: 0, masterplan_id: 10, estimated_hours: 201.75 },
      { task_id: 17, task_name: "Fix Nodus Issues", status: "completed", time_spent: 0, masterplan_id: 10, estimated_hours: 1 },
      { task_id: 30, task_name: "Buy milk", status: "pending", time_spent: 0 },
    ]);
    mockPromote.mockResolvedValue({ strategy: { id: "s9", name: "Establish Authority" }, task_deleted: true, task_id: 20 });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<TaskDashboard />);
    const buttons = await screen.findAllByRole("button", { name: /make .* a strategy/i });
    expect(buttons).toHaveLength(1);   // not the completed one, not the plan-less one
    fireEvent.click(buttons[0]);

    await waitFor(() => expect(mockPromote).toHaveBeenCalledWith(10, 20));
    expect(await screen.findByText(/is now a strategy/)).toBeInTheDocument();
  });
});
