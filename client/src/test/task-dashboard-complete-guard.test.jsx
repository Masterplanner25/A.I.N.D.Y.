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
 * Completing is a TWO-STEP interaction as of 2026-09-07: "Done" opens an inline judgement
 * step (complexity + difficulty, 1-5 each) and "Complete task" sends the request. Both feed
 * WCU, and both were permanently 1 because nothing collected them.
 *
 * These helpers keep the single-flight assertions below pointed at the button that actually
 * sends — otherwise they would assert against a button that now only opens a panel, and pass
 * for the wrong reason.
 */
const openJudgement = async () => {
  fireEvent.click(await screen.findByRole("button", { name: /Done/i }));
};

const chooseJudgement = (complexity = 3, difficulty = 4) => {
  fireEvent.click(screen.getByRole("button", { name: `Complexity ${complexity} of 5` }));
  fireEvent.click(screen.getByRole("button", { name: `Difficulty ${difficulty} of 5` }));
};

const completeButton = () => screen.getByRole("button", { name: /Complete task/i });



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
    await openJudgement();
    chooseJudgement();

    // Three clicks while the first request is still in flight — the live pattern.
    const send = completeButton();
    fireEvent.click(send);
    fireEvent.click(send);
    fireEvent.click(send);

    await waitFor(() => expect(mockCompleteTask).toHaveBeenCalledTimes(1));

    // Explicitly assert the request WAS sent, so this cannot pass by sending nothing —
    // and that the judgement travelled with it.
    expect(mockCompleteTask).toHaveBeenCalledWith("Fix Nodus Issues", {
      complexity: 3,
      difficulty: 4,
    });

    resolveCompletion({ task_result: "Completed task: Fix Nodus Issues" });
    await waitFor(() => expect(mockCompleteTask).toHaveBeenCalledTimes(1));
  });

  it("disables the button and shows a pending label while in flight", async () => {
    let resolveCompletion;
    mockCompleteTask.mockImplementation(
      () => new Promise((resolve) => { resolveCompletion = resolve; }),
    );

    render(<TaskDashboard />);
    await openJudgement();
    chooseJudgement();
    fireEvent.click(completeButton());

    const pending = await screen.findByRole("button", { name: /Completing/i });
    expect(pending).toBeDisabled();

    resolveCompletion({ task_result: "Completed task: Fix Nodus Issues" });
    await waitFor(() => expect(mockCompleteTask).toHaveBeenCalledTimes(1));
  });

  it("re-enables the button after a failure so a real retry is still possible", async () => {
    mockCompleteTask.mockRejectedValueOnce(new Error("boom"));

    render(<TaskDashboard />);
    await openJudgement();
    chooseJudgement();
    fireEvent.click(completeButton());

    await waitFor(() => expect(mockCompleteTask).toHaveBeenCalledTimes(1));
    // The guard must not latch on error — otherwise one failure permanently bricks the row.
    // The panel stays open on failure, so the judgement need not be re-entered to retry.
    await waitFor(() => expect(completeButton()).not.toBeDisabled());

    fireEvent.click(completeButton());
    await waitFor(() => expect(mockCompleteTask).toHaveBeenCalledTimes(2));
  });
});

/**
 * The estimate lands in `Task.duration`, which the MasterPlan ETA projects against, which
 * the Infinity Volume axis SUMS, and which the Trajectory axis gates on
 * (`if est_hours <= 0: continue`). Leaving it optional meant a task could be logged,
 * worked and completed while remaining invisible to two of the three axes.
 *
 * Measured 2026-09-06: completing a task created with a blank estimate moved
 * `completed_count` 1 -> 2 and left `effort_hours`, `volume_score`, `trajectory_score` and
 * `mean_pace_ratio` byte-identical.
 */
describe("TaskDashboard requires an estimate", () => {
  beforeEach(() => {
    mockGetTasks.mockReset();
    mockCreateTask.mockReset();
    mockCompleteTask.mockReset();
    mockStartTask.mockReset();
    mockGetTasks.mockResolvedValue([]);
    mockCreateTask.mockResolvedValue({});
  });

  const submit = async (taskName, hours) => {
    fireEvent.change(screen.getByPlaceholderText(/new directive|task/i), {
      target: { value: taskName },
    });
    if (hours !== undefined) {
      fireEvent.change(screen.getByPlaceholderText(/e\.g\. 1\.5/i), {
        target: { value: hours },
      });
    }
    fireEvent.click(screen.getByRole("button", { name: /^ADD$/i }));
  };

  it("marks the estimate required in the DOM, so the browser blocks it natively", async () => {
    render(<TaskDashboard />);
    await screen.findByRole("button", { name: /^ADD$/i });

    const input = screen.getByPlaceholderText(/e\.g\. 1\.5/i);
    expect(input).toBeRequired();
    // `min` rejects 0 — the value that produced an unscored task on 2026-09-06.
    expect(input).toHaveAttribute("min", "0.25");
  });

  it("sends no request when the estimate is blank", async () => {
    render(<TaskDashboard />);
    await screen.findByRole("button", { name: /^ADD$/i });

    await submit("Close A.I.N.D.Y. PR");

    // Native constraint validation stops the submit before the handler runs, so there is
    // no toast to assert here — the outcome that matters is that nothing was created.
    await waitFor(() => expect(mockCreateTask).not.toHaveBeenCalled());
  });

  it("the JS guard is a real backstop, not just the DOM attribute", async () => {
    // `fireEvent.submit` bypasses constraint validation, which is what a programmatic
    // submit or a browser without it would do. The handler must still refuse.
    const { container } = render(<TaskDashboard />);
    await screen.findByRole("button", { name: /^ADD$/i });

    fireEvent.change(screen.getByPlaceholderText(/new directive|task/i), {
      target: { value: "Close A.I.N.D.Y. PR" },
    });
    fireEvent.change(screen.getByPlaceholderText(/e\.g\. 1\.5/i), { target: { value: "0" } });
    fireEvent.submit(container.querySelector("form"));

    await waitFor(() => expect(screen.getByText(/An estimate is required/i)).toBeTruthy());
    expect(mockCreateTask).not.toHaveBeenCalled();
  });

  it("sends estimated_hours when one is given", async () => {
    render(<TaskDashboard />);
    await screen.findByRole("button", { name: /^ADD$/i });

    await submit("Close A.I.N.D.Y. PR", "0.25");

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
    expect(mockCreateTask).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Close A.I.N.D.Y. PR", estimated_hours: 0.25 }),
    );
  });

  it("sends one create when ADD is pressed repeatedly", async () => {
    let resolveCreate;
    mockCreateTask.mockImplementation(
      () => new Promise((resolve) => { resolveCreate = resolve; }),
    );

    render(<TaskDashboard />);
    await screen.findByRole("button", { name: /^ADD$/i });

    fireEvent.change(screen.getByPlaceholderText(/new directive|task/i), {
      target: { value: "Close A.I.N.D.Y. PR" },
    });
    fireEvent.change(screen.getByPlaceholderText(/e\.g\. 1\.5/i), { target: { value: "0.25" } });

    const addButton = screen.getByRole("button", { name: /^ADD$/i });
    fireEvent.click(addButton);
    fireEvent.click(addButton);
    fireEvent.click(addButton);

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("button", { name: /ADDING/i })).toBeDisabled();

    resolveCreate({});
    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
  });
});
