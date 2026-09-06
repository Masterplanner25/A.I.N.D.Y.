import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { mockGetTasks, mockCreateTask, mockCompleteTask, mockStartTask } = vi.hoisted(() => ({
  mockGetTasks: vi.fn(),
  mockCreateTask: vi.fn(),
  mockCompleteTask: vi.fn(),
  mockStartTask: vi.fn(),
}));

vi.mock("../api/tasks.js", () => ({
  getTasks: mockGetTasks,
  createTask: mockCreateTask,
  completeTask: mockCompleteTask,
  startTask: mockStartTask,
}));

import TaskDashboard from "../components/app/TaskDashboard";

/**
 * Completing a task runs the whole `task_completion` flow — memory capture, downstream
 * unlock, ETA recalc and a full Infinity re-score — which took ~14s on the live stack.
 * Until this guard the button had no disabled state and no pending label, and
 * `velocityMessage` is only set after the await resolves, so nothing acknowledged the
 * click for fourteen seconds and the button invited re-clicking.
 *
 * Measured 2026-09-06: one completion reached the API as 4 `tasks.complete` calls,
 * producing 4 `task_completion` flow runs and duplicate score_history /
 * three_axis_shadow_records rows — one with score_delta = 0. The server-side fix is
 * `task_orchestrate`'s repeat guard; this is the layer that stops the extra requests
 * being sent at all.
 */
describe("TaskDashboard completion is single-flight", () => {
  beforeEach(() => {
    mockGetTasks.mockReset();
    mockCreateTask.mockReset();
    mockCompleteTask.mockReset();
    mockStartTask.mockReset();
    mockGetTasks.mockResolvedValue([
      { task_name: "Fix Nodus Issues", status: "in_progress", priority: 1 },
    ]);
  });

  it("sends one request when the Done button is clicked repeatedly", async () => {
    let resolveCompletion;
    mockCompleteTask.mockImplementation(
      () => new Promise((resolve) => { resolveCompletion = resolve; }),
    );

    render(<TaskDashboard />);
    const doneButton = await screen.findByRole("button", { name: /Done/i });

    // Three clicks while the first request is still in flight — the live pattern.
    fireEvent.click(doneButton);
    fireEvent.click(doneButton);
    fireEvent.click(doneButton);

    await waitFor(() => expect(mockCompleteTask).toHaveBeenCalledTimes(1));

    // Explicitly assert the request WAS sent, so this cannot pass by sending nothing.
    expect(mockCompleteTask).toHaveBeenCalledWith("Fix Nodus Issues");

    resolveCompletion({ task_result: "Completed task: Fix Nodus Issues" });
    await waitFor(() => expect(mockCompleteTask).toHaveBeenCalledTimes(1));
  });

  it("disables the button and shows a pending label while in flight", async () => {
    let resolveCompletion;
    mockCompleteTask.mockImplementation(
      () => new Promise((resolve) => { resolveCompletion = resolve; }),
    );

    render(<TaskDashboard />);
    fireEvent.click(await screen.findByRole("button", { name: /Done/i }));

    const pending = await screen.findByRole("button", { name: /Completing/i });
    expect(pending).toBeDisabled();

    resolveCompletion({ task_result: "Completed task: Fix Nodus Issues" });
    await waitFor(() => expect(pending).not.toBeDisabled());
  });

  it("re-enables the button after a failure so a real retry is still possible", async () => {
    mockCompleteTask.mockRejectedValueOnce(new Error("boom"));

    render(<TaskDashboard />);
    const doneButton = await screen.findByRole("button", { name: /Done/i });
    fireEvent.click(doneButton);

    await waitFor(() => expect(mockCompleteTask).toHaveBeenCalledTimes(1));
    // The guard must not latch on error — otherwise one failure permanently bricks the row.
    await waitFor(() => expect(doneButton).not.toBeDisabled());

    fireEvent.click(doneButton);
    await waitFor(() => expect(mockCompleteTask).toHaveBeenCalledTimes(2));
  });
});
