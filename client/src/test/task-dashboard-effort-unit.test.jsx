import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// The estimate is typed in the unit a person thinks in and sent in hours, the unit the
// math wants. "About five weeks" used to be typed as 201.75 by hand.

const { mockGetTasks, mockCreateTask, mockListMasterPlans } = vi.hoisted(() => ({
  mockGetTasks: vi.fn(),
  mockCreateTask: vi.fn(),
  mockListMasterPlans: vi.fn(),
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
  getStrategyLayer: vi.fn(),
}));

import TaskDashboard from "../components/app/TaskDashboard";

describe("TaskDashboard — estimate unit", () => {
  beforeEach(() => {
    mockGetTasks.mockReset();
    mockCreateTask.mockReset();
    mockListMasterPlans.mockReset();
    mockGetTasks.mockResolvedValue([]);
    mockCreateTask.mockResolvedValue({});
    mockListMasterPlans.mockResolvedValue({ plans: [] });
  });

  it("sends weeks as hours and previews the conversion", async () => {
    render(<TaskDashboard />);
    await waitFor(() => expect(mockGetTasks).toHaveBeenCalled());

    fireEvent.change(screen.getByPlaceholderText(/initialize new directive/i), {
      target: { value: "Establish Authority" },
    });
    fireEvent.change(screen.getByLabelText(/estimate unit/i), { target: { value: "weeks" } });
    fireEvent.change(screen.getByPlaceholderText(/e\.g\. 1\.5/i), { target: { value: "5" } });

    expect(screen.getByText("= 200h")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /add/i }));

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalled());
    expect(mockCreateTask.mock.calls[0][0].estimated_hours).toBe(200);
  });

  it("shows each estimate back in a readable unit", async () => {
    mockGetTasks.mockResolvedValue([
      { task_name: "Fix Nodus Issues", status: "completed", time_spent: 0, estimated_hours: 1 },
      { task_name: "Establish Authority", status: "in_progress", time_spent: 0, estimated_hours: 201.75 },
    ]);

    render(<TaskDashboard />);

    expect(await screen.findByText(/Est: 1h/)).toBeInTheDocument();
    expect(screen.getByText(/Est: 1\.2 mo/)).toBeInTheDocument();
  });
});
