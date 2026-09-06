import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { mockGetTasks, mockCreateTask, mockCompleteTask, mockStartTask, mockDeleteTask } =
  vi.hoisted(() => ({
    mockGetTasks: vi.fn(),
    mockCreateTask: vi.fn(),
    mockCompleteTask: vi.fn(),
    mockStartTask: vi.fn(),
    mockDeleteTask: vi.fn(),
  }));

vi.mock("../api/tasks.js", () => ({
  getTasks: mockGetTasks,
  createTask: mockCreateTask,
  completeTask: mockCompleteTask,
  startTask: mockStartTask,
  deleteTask: mockDeleteTask,
}));

import TaskDashboard from "../components/app/TaskDashboard";

/**
 * The delete capability existed as `sys.v1.task.delete_by_ids` with no HTTP route and no
 * UI, reachable only from `masterplan_execution_service`. A task created by mistake could
 * not be removed by the person who created it — two duplicates had to be deleted straight
 * from the database on 2026-09-06.
 */
describe("TaskDashboard delete", () => {
  const confirmTrue = () => vi.spyOn(window, "confirm").mockReturnValue(true);

  beforeEach(() => {
    mockGetTasks.mockReset();
    mockCreateTask.mockReset();
    mockCompleteTask.mockReset();
    mockStartTask.mockReset();
    mockDeleteTask.mockReset();
    mockDeleteTask.mockResolvedValue({ deleted_count: 1 });
    mockGetTasks.mockResolvedValue([
      { task_name: "Close A.I.N.D.Y. PR", status: "pending", priority: 1 },
    ]);
  });

  afterEach(() => vi.restoreAllMocks());

  it("deletes the task after confirmation", async () => {
    confirmTrue();
    render(<TaskDashboard />);

    fireEvent.click(await screen.findByRole("button", { name: /Delete Close A\.I\.N\.D\.Y\. PR/i }));

    await waitFor(() => expect(mockDeleteTask).toHaveBeenCalledWith("Close A.I.N.D.Y. PR"));
    // The list must refetch, or the deleted row stays on screen.
    await waitFor(() => expect(mockGetTasks).toHaveBeenCalledTimes(2));
  });

  it("does nothing when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<TaskDashboard />);

    fireEvent.click(await screen.findByRole("button", { name: /Delete Close A\.I\.N\.D\.Y\. PR/i }));

    // Deletion is irreversible — a declined confirm must send nothing at all.
    await waitFor(() => expect(mockDeleteTask).not.toHaveBeenCalled());
  });

  it("sends one request when Delete is pressed repeatedly", async () => {
    confirmTrue();
    let resolveDelete;
    mockDeleteTask.mockImplementation(
      () => new Promise((resolve) => { resolveDelete = resolve; }),
    );

    render(<TaskDashboard />);
    const btn = await screen.findByRole("button", { name: /Delete Close A\.I\.N\.D\.Y\. PR/i });

    fireEvent.click(btn);
    fireEvent.click(btn);
    fireEvent.click(btn);

    await waitFor(() => expect(mockDeleteTask).toHaveBeenCalledTimes(1));
    resolveDelete({ deleted_count: 1 });
  });

  it("stays available for a completed task", async () => {
    mockGetTasks.mockResolvedValue([
      { task_name: "Fix Nodus Issues", status: "completed", priority: 1 },
    ]);
    render(<TaskDashboard />);

    // Start/Done are hidden once completed; Delete must not be, since a task completed by
    // mistake is exactly the one you want to remove.
    expect(await screen.findByRole("button", { name: /Delete Fix Nodus Issues/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Done/i })).toBeNull();
  });

  it("shows a toast and re-enables the button when the delete fails", async () => {
    confirmTrue();
    mockDeleteTask.mockRejectedValueOnce(new Error("Task 'X' not found"));
    render(<TaskDashboard />);

    const btn = await screen.findByRole("button", { name: /Delete Close A\.I\.N\.D\.Y\. PR/i });
    fireEvent.click(btn);

    await waitFor(() => expect(screen.getByText(/not found/i)).toBeTruthy());
    await waitFor(() => expect(btn).not.toBeDisabled());
  });
});
