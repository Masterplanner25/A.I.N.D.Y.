import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// The plan's phases, and the phase-advance proposal — STRATEGY_LAYER_SPEC §8 step 3b.
// The pattern under test is "system proposes, human confirms": the only button agrees
// with something the system already said, and a refused confirmation is shown as the
// API's own sentence rather than swallowed.

const {
  mockGetStrategyLayer, mockGetPhaseAdvanceProposal, mockConfirmPhaseAdvance,
  mockDismissPhaseAdvance, mockReopenPhase,
} = vi.hoisted(() => ({
  mockGetStrategyLayer: vi.fn(),
  mockGetPhaseAdvanceProposal: vi.fn(),
  mockConfirmPhaseAdvance: vi.fn(),
  mockDismissPhaseAdvance: vi.fn(),
  mockReopenPhase: vi.fn(),
}));

vi.mock("../api/masterplan.js", () => ({
  getStrategyLayer: mockGetStrategyLayer,
  getPhaseAdvanceProposal: mockGetPhaseAdvanceProposal,
  confirmPhaseAdvance: mockConfirmPhaseAdvance,
  dismissPhaseAdvance: mockDismissPhaseAdvance,
  reopenPhase: mockReopenPhase,
}));

import PhasePanel from "../components/app/PhasePanel";

const PHASES = [
  { id: "p1", ordinal: 1, name: "Foundation Building", status: "pending" },
  { id: "p2", ordinal: 2, name: "Platform Development", status: "pending" },
  { id: "p3", ordinal: 3, name: "Expansion and Scaling", status: "pending" },
];

const EARLY_PROPOSAL = {
  proposed: true,
  reason: "work_complete",
  phase: PHASES[0],
  next_phase: PHASES[1],
  evidence: { tasks_total: 2, tasks_completed: 2, open_task_ids: [], early_by_days: 360 },
};

describe("PhasePanel", () => {
  beforeEach(() => {
    mockGetStrategyLayer.mockReset();
    mockGetPhaseAdvanceProposal.mockReset();
    mockConfirmPhaseAdvance.mockReset();
    mockDismissPhaseAdvance.mockReset();
    mockReopenPhase.mockReset();
  });

  it("renders nothing for a plan that predates the layer", async () => {
    mockGetStrategyLayer.mockResolvedValue({ phases: [] });
    mockGetPhaseAdvanceProposal.mockResolvedValue({ proposed: false, reason: "no_phases" });

    const { container } = render(<PhasePanel planId={10} />);

    await waitFor(() => expect(mockGetStrategyLayer).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("lists the phases and shows no proposal when there is none", async () => {
    mockGetStrategyLayer.mockResolvedValue({ phases: PHASES });
    mockGetPhaseAdvanceProposal.mockResolvedValue({
      proposed: false, phase: PHASES[0], next_phase: PHASES[1],
      evidence: { tasks_total: 2, tasks_completed: 1, open_task_ids: [18], early_by_days: null },
    });

    render(<PhasePanel planId={10} />);

    expect(await screen.findByText(/1\. Foundation Building/)).toBeInTheDocument();
    expect(screen.getByText(/3\. Expansion and Scaling/)).toBeInTheDocument();
    expect(screen.queryByTestId("phase-advance-proposal")).not.toBeInTheDocument();
  });

  it("shows the early-completion proposal with the number the review opens with", async () => {
    mockGetStrategyLayer.mockResolvedValue({ phases: PHASES });
    mockGetPhaseAdvanceProposal.mockResolvedValue(EARLY_PROPOSAL);

    render(<PhasePanel planId={10} />);

    const card = await screen.findByTestId("phase-advance-proposal");
    expect(card).toHaveTextContent("Foundation Building looks done.");
    expect(card).toHaveTextContent("All 2 of its tasks are complete, 360 days inside its window.");
    expect(card).toHaveTextContent("Confirming opens Platform Development.");
  });

  it("confirming closes the phase, reloads, and shows the review", async () => {
    mockGetStrategyLayer
      .mockResolvedValueOnce({ phases: PHASES })
      .mockResolvedValueOnce({ phases: [
        { ...PHASES[0], status: "complete" }, { ...PHASES[1], status: "active" }, PHASES[2],
      ] });
    mockGetPhaseAdvanceProposal
      .mockResolvedValueOnce(EARLY_PROPOSAL)
      .mockResolvedValueOnce({ proposed: false, phase: PHASES[1], evidence: {} });
    mockConfirmPhaseAdvance.mockResolvedValue({
      completed: { ...PHASES[0], status: "complete" },
      activated: { ...PHASES[1], status: "active" },
      plan_phase: 2,
      review: { reason: "work_complete", early_by_days: 360, moved_task_ids: [], moved_to_phase_id: null },
    });

    render(<PhasePanel planId={10} />);
    fireEvent.click(await screen.findByRole("button", { name: /confirm/i }));

    const review = await screen.findByTestId("phase-advance-review");
    expect(mockConfirmPhaseAdvance).toHaveBeenCalledWith(10, "p1");
    expect(review).toHaveTextContent("Foundation Building closed.");
    expect(review).toHaveTextContent("Platform Development is now active.");
    expect(review).toHaveTextContent("Finished 360 days early");
    expect(screen.queryByTestId("phase-advance-proposal")).not.toBeInTheDocument();
    expect(screen.getByText("complete")).toBeInTheDocument();
  });

  it("names the work that moved when a phase overran", async () => {
    mockGetStrategyLayer.mockResolvedValue({ phases: PHASES });
    mockGetPhaseAdvanceProposal
      .mockResolvedValueOnce({
        proposed: true, reason: "window_elapsed", phase: PHASES[0], next_phase: PHASES[1],
        evidence: { tasks_total: 2, tasks_completed: 1, open_task_ids: [18], early_by_days: null },
      })
      .mockResolvedValue({ proposed: false });
    mockConfirmPhaseAdvance.mockResolvedValue({
      completed: PHASES[0], activated: PHASES[1], plan_phase: 2,
      review: { reason: "window_elapsed", early_by_days: null, moved_task_ids: [18], moved_to_phase_id: "p2" },
    });

    render(<PhasePanel planId={10} />);
    expect(await screen.findByTestId("phase-advance-proposal")).toHaveTextContent(
      "Its window has ended with 1 task still open (1 of 2 complete).",
    );
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    expect(await screen.findByTestId("phase-advance-review")).toHaveTextContent(
      "1 open task moved into Platform Development",
    );
  });

  it("shows the API's own sentence when confirmation is refused", async () => {
    mockGetStrategyLayer.mockResolvedValue({ phases: PHASES });
    mockGetPhaseAdvanceProposal.mockResolvedValue(EARLY_PROPOSAL);
    const err = new Error("API Error (409): ...");
    err.status = 409;
    err.body = JSON.stringify({ detail: {
      error: "phase_advance_refused",
      message: "phase 'Foundation Building' is not the plan's current phase; 'Platform Development' is",
    } });
    mockConfirmPhaseAdvance.mockRejectedValue(err);

    render(<PhasePanel planId={10} />);
    fireEvent.click(await screen.findByRole("button", { name: /confirm/i }));

    expect(await screen.findByText(/is not the plan's current phase/)).toBeInTheDocument();
    expect(screen.queryByTestId("phase-advance-review")).not.toBeInTheDocument();
  });

  // ── "what if the phase isn't complete?" ───────────────────────────────────────────

  it("NOT DONE dismisses the proposal and says when it will return", async () => {
    mockGetStrategyLayer.mockResolvedValue({ phases: PHASES });
    mockGetPhaseAdvanceProposal
      .mockResolvedValueOnce(EARLY_PROPOSAL)
      .mockResolvedValue({
        ...EARLY_PROPOSAL, proposed: false,
        dismissed: { at: "2026-09-10T20:00:00+00:00", task_count: 2 },
      });
    mockDismissPhaseAdvance.mockResolvedValue({
      phase: PHASES[0], dismissed: { at: "2026-09-10T20:00:00+00:00", task_count: 2 },
      returns_when: "the phase's attached tasks change",
    });

    render(<PhasePanel planId={10} />);
    fireEvent.click(await screen.findByRole("button", { name: /not done/i }));

    expect(mockDismissPhaseAdvance).toHaveBeenCalledWith(10, "p1");
    expect(await screen.findByTestId("phase-advance-notice")).toHaveTextContent(
      "Foundation Building stays open — the proposal comes back when its tasks change",
    );
    expect(screen.queryByTestId("phase-advance-proposal")).not.toBeInTheDocument();
    expect(screen.getByTestId("phase-advance-dismissed")).toHaveTextContent(
      "You said Foundation Building is not done, with 2 tasks attached.",
    );
    expect(screen.queryByTestId("phase-advance-review")).not.toBeInTheDocument();
  });

  it("offers REOPEN only on the most recently closed phase, and it reverses the close", async () => {
    const closed = [
      { ...PHASES[0], status: "complete" },
      { ...PHASES[1], status: "complete" },
      { ...PHASES[2], status: "active" },
    ];
    mockGetStrategyLayer
      .mockResolvedValueOnce({ phases: closed })
      .mockResolvedValue({ phases: [closed[0], { ...PHASES[1], status: "active" }, PHASES[2]] });
    mockGetPhaseAdvanceProposal.mockResolvedValue({ proposed: false, phase: PHASES[2], evidence: {} });
    mockReopenPhase.mockResolvedValue({
      reopened: { ...PHASES[1], status: "active" }, stepped_back: PHASES[2], plan_phase: 2,
    });

    render(<PhasePanel planId={10} />);

    const buttons = await screen.findAllByRole("button", { name: /reopen/i });
    expect(buttons).toHaveLength(1);
    expect(buttons[0].closest("li")).toHaveTextContent("Platform Development");

    fireEvent.click(buttons[0]);

    expect(mockReopenPhase).toHaveBeenCalledWith(10, "p2");
    expect(await screen.findByTestId("phase-advance-notice")).toHaveTextContent(
      "Platform Development reopened. Expansion and Scaling is pending again.",
    );
  });
});
