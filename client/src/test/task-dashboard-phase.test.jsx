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

  it("the promoted strategy is in the picker immediately, without leaving the page", async () => {
    // Found live 2026-09-10: promote, then try to add a task under the new strategy — not in
    // the dropdown until the page was left and re-entered.
    mockGetTasks.mockResolvedValue([
      { task_id: 21, task_name: "Build IP", status: "in_progress", time_spent: 0, masterplan_id: 10, estimated_hours: 205 },
    ]);
    // The layer is what the server says at the moment of the call: the strategy exists only
    // after promotion. (The list also loads the layer for grouping, so calls are not counted.)
    let promoted = false;
    mockGetStrategyLayer.mockImplementation(async () => ({
      phases: PHASES,
      strategies: promoted ? [...STRATEGIES, { id: "s9", phase_id: "p1", name: "Build IP", status: "active" }] : STRATEGIES,
    }));
    mockPromote.mockImplementation(async () => {
      promoted = true;
      return { strategy: { id: "s9", name: "Build IP" }, task_deleted: true, task_id: 21 };
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<TaskDashboard />);
    await waitFor(() => expect(mockListMasterPlans).toHaveBeenCalled());
    fireEvent.change(await screen.findByLabelText(/masterplan/i), { target: { value: "10" } });
    await screen.findByLabelText(/^strategy$/i);
    expect(screen.getByLabelText(/^strategy$/i)).not.toHaveTextContent("Build IP");

    fireEvent.click(await screen.findByRole("button", { name: /make build ip a strategy/i }));

    await waitFor(() => expect(mockPromote).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByLabelText(/^strategy$/i)).toHaveTextContent("Build IP"));
  });

  it("groups tasks under the strategy they serve, with the phase and a done count", async () => {
    // The owner's first reaction to promotion was "all of it disappeared": the promoted rows
    // left this list with nothing to say where they went.
    mockGetTasks.mockResolvedValue([
      { task_id: 24, task_name: "Host a Live Vibe Coding Session", status: "pending", time_spent: 0, masterplan_id: 10, strategy_id: "s1", estimated_hours: 1 },
      { task_id: 26, task_name: "Write three essays", status: "completed", time_spent: 0, masterplan_id: 10, strategy_id: "s1", estimated_hours: 6 },
      { task_id: 22, task_name: "Build a working technical prototype", status: "in_progress", time_spent: 0, masterplan_id: 10, estimated_hours: 194 },
      { task_id: 30, task_name: "Buy milk", status: "pending", time_spent: 0 },
    ]);

    render(<TaskDashboard />);

    // The header appears with the tasks; the strategy's name and phase arrive with the layer a
    // tick later, so wait on the text rather than the element.
    await waitFor(() => expect(screen.getByTestId("strategy-group")).toHaveTextContent(
      "STRATEGYEstablish Authority· Foundation Building1/2 done",
    ));
    const group = screen.getByRole("region", { name: /strategy establish authority/i });
    expect(group).toHaveTextContent("Host a Live Vibe Coding Session");
    expect(group).toHaveTextContent("Write three essays");
    expect(group).not.toHaveTextContent("Buy milk");
    const none = screen.getByRole("region", { name: /tasks with no strategy/i });
    expect(none).toHaveTextContent("NO STRATEGY");
    expect(none).toHaveTextContent("Build a working technical prototype");
    expect(none).toHaveTextContent("Buy milk");
  });

  it("does not draw a NO STRATEGY header when nothing has a strategy", async () => {
    mockGetTasks.mockResolvedValue([{ task_id: 30, task_name: "Buy milk", status: "pending", time_spent: 0 }]);

    render(<TaskDashboard />);

    expect(await screen.findByText("Buy milk")).toBeInTheDocument();
    expect(screen.queryByText("NO STRATEGY")).not.toBeInTheDocument();
  });
});
