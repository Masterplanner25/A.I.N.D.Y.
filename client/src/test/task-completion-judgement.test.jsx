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
 * WCU — Work Complexity Units — is `effort_hours x task_complexity x task_difficulty`, and
 * it is the only universal measure of work done this repo has. Two of its three terms were
 * inert: every task carried `task_complexity = 1` and `task_difficulty = 1`, the column
 * defaults, because nothing ever set them. So WCU silently reduced to estimated hours, which
 * `Task.duration` already reports (MASTERPLAN_GOAL_ATTAINMENT_SPEC §4b).
 *
 * Collected at COMPLETION rather than creation, on the owner's call: difficulty guessed up
 * front is a guess, difficulty recorded afterwards is an observation — and WCU only accrues
 * from completed tasks, so nothing is lost by waiting.
 *
 * ★ The assertions below are mostly about what must NOT happen. A judgement that can be
 * clicked past, or that pre-selects a middle value, produces fabricated data that is
 * indistinguishable from real data — the failure mode the worth-declaration spec is built
 * around, and the reason these columns sitting at 1 went unnoticed for so long.
 */
describe("Task completion judgement", () => {
  beforeEach(() => {
    mockGetTasks.mockReset();
    mockCreateTask.mockReset();
    mockCompleteTask.mockReset();
    mockStartTask.mockReset();
    mockDeleteTask.mockReset();
    mockCompleteTask.mockResolvedValue({ task_result: "Completed task: Fix Nodus Issues" });
    mockGetTasks.mockResolvedValue([
      { task_name: "Fix Nodus Issues", status: "in_progress", priority: 1 },
    ]);
  });

  const openJudgement = async () => {
    fireEvent.click(await screen.findByRole("button", { name: /Done/i }));
  };

  const pick = (label, n) =>
    fireEvent.click(screen.getByRole("button", { name: `${label} ${n} of 5` }));

  const completeButton = () => screen.getByRole("button", { name: /Complete task/i });

  // ── the judgement must be taken, not assumed ─────────────────────────────────────────

  it("does not complete the task straight from Done", async () => {
    render(<TaskDashboard />);
    await openJudgement();

    // Done now opens the step. Completing without a judgement is the behaviour being removed.
    await waitFor(() => expect(mockCompleteTask).not.toHaveBeenCalled());
    expect(completeButton()).toBeTruthy();
  });

  it("pre-selects nothing", async () => {
    render(<TaskDashboard />);
    await openJudgement();

    // A pre-selected middle value would be recorded verbatim by anyone clicking through,
    // which is fabricated data wearing the shape of a judgement.
    for (const n of [1, 2, 3, 4, 5]) {
      expect(screen.getByRole("button", { name: `Complexity ${n} of 5` }))
        .toHaveAttribute("aria-pressed", "false");
      expect(screen.getByRole("button", { name: `Difficulty ${n} of 5` }))
        .toHaveAttribute("aria-pressed", "false");
    }
  });

  it("cannot be completed until BOTH values are chosen", async () => {
    render(<TaskDashboard />);
    await openJudgement();

    expect(completeButton()).toBeDisabled();

    pick("Complexity", 4);
    expect(completeButton()).toBeDisabled();  // one is not enough

    pick("Difficulty", 2);
    expect(completeButton()).not.toBeDisabled();
  });

  // ── the judgement must reach the API ─────────────────────────────────────────────────

  it("sends both values with the completion", async () => {
    render(<TaskDashboard />);
    await openJudgement();
    pick("Complexity", 5);
    pick("Difficulty", 2);
    fireEvent.click(completeButton());

    await waitFor(() =>
      expect(mockCompleteTask).toHaveBeenCalledWith("Fix Nodus Issues", {
        complexity: 5,
        difficulty: 2,
      }),
    );
  });

  it("sends the last value chosen when one is changed", async () => {
    render(<TaskDashboard />);
    await openJudgement();
    pick("Complexity", 1);
    pick("Complexity", 4);   // changed mind
    pick("Difficulty", 3);
    fireEvent.click(completeButton());

    await waitFor(() =>
      expect(mockCompleteTask).toHaveBeenCalledWith("Fix Nodus Issues", {
        complexity: 4,
        difficulty: 3,
      }),
    );
  });

  it("marks the chosen value as pressed", async () => {
    render(<TaskDashboard />);
    await openJudgement();
    pick("Complexity", 3);

    expect(screen.getByRole("button", { name: "Complexity 3 of 5" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Complexity 4 of 5" }))
      .toHaveAttribute("aria-pressed", "false");
  });

  // ── it must be escapable ─────────────────────────────────────────────────────────────

  it("cancel leaves the task untouched", async () => {
    render(<TaskDashboard />);
    await openJudgement();
    pick("Complexity", 3);
    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));

    await waitFor(() => expect(mockCompleteTask).not.toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Complete task/i })).toBeNull();
  });

  it("re-opening after a cancel starts blank", async () => {
    render(<TaskDashboard />);
    await openJudgement();
    pick("Complexity", 5);
    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    await openJudgement();

    // A retained selection would let a previous task's judgement be submitted for this one.
    expect(screen.getByRole("button", { name: "Complexity 5 of 5" }))
      .toHaveAttribute("aria-pressed", "false");
    expect(completeButton()).toBeDisabled();
  });
});
