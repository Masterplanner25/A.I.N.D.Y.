import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// The plan's phases, and the phase-advance proposal — STRATEGY_LAYER_SPEC §8 step 3b.
// The pattern under test is "system proposes, human confirms": the only button agrees
// with something the system already said, and a refused confirmation is shown as the
// API's own sentence rather than swallowed.

const {
  mockGetStrategyLayer, mockGetPhaseAdvanceProposal, mockConfirmPhaseAdvance,
  mockDismissPhaseAdvance, mockReopenPhase,
  mockCreateStrategy, mockStartStrategy, mockFinishStrategy, mockSetStrategyObjective,
} = vi.hoisted(() => ({
  mockGetStrategyLayer: vi.fn(),
  mockGetPhaseAdvanceProposal: vi.fn(),
  mockConfirmPhaseAdvance: vi.fn(),
  mockDismissPhaseAdvance: vi.fn(),
  mockReopenPhase: vi.fn(),
  mockCreateStrategy: vi.fn(),
  mockStartStrategy: vi.fn(),
  mockFinishStrategy: vi.fn(),
  mockSetStrategyObjective: vi.fn(),
}));

vi.mock("../api/masterplan.js", () => ({
  getStrategyLayer: mockGetStrategyLayer,
  getPhaseAdvanceProposal: mockGetPhaseAdvanceProposal,
  confirmPhaseAdvance: mockConfirmPhaseAdvance,
  dismissPhaseAdvance: mockDismissPhaseAdvance,
  reopenPhase: mockReopenPhase,
  createStrategy: mockCreateStrategy,
  startStrategy: mockStartStrategy,
  finishStrategy: mockFinishStrategy,
  setStrategyObjective: mockSetStrategyObjective,
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
    mockCreateStrategy.mockReset();
    mockStartStrategy.mockReset();
    mockFinishStrategy.mockReset();
    mockSetStrategyObjective.mockReset();
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
    expect(card).toHaveTextContent("All of its work is done — 2 of 2 tasks complete, 360 days inside its window.");
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
      "Its window has ended with 1 thing still open (1 of 2 tasks complete).",
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

  it("shows each phase's attached work, and names the work the layer cannot see", async () => {
    mockGetStrategyLayer.mockResolvedValue({
      phases: PHASES,
      task_counts: { p1: { total: 3, completed: 2 }, unphased: { total: 1, completed: 0 } },
    });
    mockGetPhaseAdvanceProposal.mockResolvedValue({ proposed: false, phase: PHASES[0], evidence: {} });

    render(<PhasePanel planId={10} />);

    const first = (await screen.findByText(/1\. Foundation Building/)).closest("li");
    expect(first).toHaveTextContent("2/3");
    expect(screen.getByText(/1 task on this plan has no phase/)).toBeInTheDocument();
  });

  // ── strategies: how the current phase gets done ────────────────────────────────

  const STRATEGIES = [
    { id: "s1", phase_id: "p1", name: "Establish Authority", status: "active", outcome: null },
    { id: "s2", phase_id: "p1", name: "Build IP", status: "proposed", outcome: null },
    { id: "s3", phase_id: "p1", name: "Guest posts", status: "abandoned", outcome: "did_not_work" },
  ];

  it("lists the current phase's strategies with status, attribution and the right verbs", async () => {
    mockGetStrategyLayer.mockResolvedValue({
      phases: PHASES, strategies: STRATEGIES,
      strategy_task_counts: { s1: { total: 3, completed: 1, hours_total: 16, hours_completed: 6 } },
    });
    mockGetPhaseAdvanceProposal.mockResolvedValue({ proposed: false, phase: PHASES[0], evidence: {} });

    render(<PhasePanel planId={10} />);

    const box = await screen.findByTestId("phase-strategies");
    expect(box).toHaveTextContent("Establish Authority");
    expect(box).toHaveTextContent("1/3 tasks · 6h of 2 d");
    expect(box).toHaveTextContent("abandoned · did not work");
    expect(screen.getAllByRole("button", { name: /^start$/i })).toHaveLength(1);     // only the proposed one
    expect(screen.getAllByRole("button", { name: /finish/i })).toHaveLength(2);      // not the abandoned one
  });

  it("adds a strategy to the current phase", async () => {
    mockGetStrategyLayer.mockResolvedValue({ phases: PHASES, strategies: [] });
    mockGetPhaseAdvanceProposal.mockResolvedValue({ proposed: false, phase: PHASES[0], evidence: {} });
    mockCreateStrategy.mockResolvedValue({ id: "s9", name: "Establish Authority", phase_id: "p1", status: "proposed" });

    render(<PhasePanel planId={10} />);
    fireEvent.change(await screen.findByLabelText(/new strategy/i), { target: { value: "Establish Authority" } });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(mockCreateStrategy).toHaveBeenCalledWith(10, { name: "Establish Authority", phase_id: "p1" }));
  });

  it("finishing offers the four verdicts, and abandoning says what was released", async () => {
    mockGetStrategyLayer.mockResolvedValue({ phases: PHASES, strategies: [STRATEGIES[0]] });
    mockGetPhaseAdvanceProposal.mockResolvedValue({ proposed: false, phase: PHASES[0], evidence: {} });
    mockFinishStrategy.mockResolvedValue({ ...STRATEGIES[0], status: "abandoned", outcome: "did_not_work", tasks_released: 2 });

    render(<PhasePanel planId={10} />);
    fireEvent.click(await screen.findByRole("button", { name: /finish/i }));

    const menu = screen.getByTestId("strategy-verdict");
    expect(menu).toHaveTextContent("WORKED");
    expect(menu).toHaveTextContent("DID NOT WORK");
    expect(menu).toHaveTextContent("DISPLACED");
    fireEvent.click(screen.getByRole("button", { name: /did not work/i }));

    await waitFor(() => expect(mockFinishStrategy).toHaveBeenCalledWith(10, "s1", "abandon", { outcome: undefined }));
    expect(await screen.findByTestId("phase-advance-notice")).toHaveTextContent(
      "Establish Authority abandoned. 2 open tasks returned to the plan; completed work stays attached.",
    );
  });

  // ── objectives: worked toward THIS ─────────────────────────────────────────────

  const OBJECTIVES = [
    { id: "o1", name: "Ethical AI Framework", intent: "guidelines", ordinal: 1 },
    { id: "o2", name: "Partnership Development", intent: "alliances", ordinal: 2 },
  ];

  it("shows each objective's attributed work, and the work no objective can claim", async () => {
    mockGetStrategyLayer.mockResolvedValue({
      phases: PHASES, objectives: OBJECTIVES,
      strategies: [{ ...STRATEGIES[0], objective_id: "o1" }, STRATEGIES[1]],
      objective_rollup: {
        o1: { strategies: 1, strategies_by_status: { active: 1 }, tasks: 3, completed: 1, hours_total: 16, hours_completed: 6 },
        unhoused: { strategies: 1, strategies_by_status: { proposed: 1 }, tasks: 1, completed: 0, hours_total: 8, hours_completed: 0 },
      },
    });
    mockGetPhaseAdvanceProposal.mockResolvedValue({ proposed: false, phase: PHASES[0], evidence: {} });

    render(<PhasePanel planId={10} />);

    const box = await screen.findByTestId("plan-objectives");
    expect(box).toHaveTextContent("Ethical AI Framework1 strategy · 6h of 2 d");
    expect(box).toHaveTextContent("Partnership Developmentnothing serves this yet");
    expect(box).toHaveTextContent("1 strategy serves no objective — 0h of 1 d that no objective can claim.");
  });

  it("housing a strategy under an objective is one picker on the strategy", async () => {
    mockGetStrategyLayer.mockResolvedValue({ phases: PHASES, objectives: OBJECTIVES, strategies: [STRATEGIES[1]] });
    mockGetPhaseAdvanceProposal.mockResolvedValue({ proposed: false, phase: PHASES[0], evidence: {} });
    mockSetStrategyObjective.mockResolvedValue({ ...STRATEGIES[1], objective_id: "o2" });

    render(<PhasePanel planId={10} />);
    fireEvent.change(await screen.findByLabelText("Build IP serves"), { target: { value: "o2" } });

    await waitFor(() => expect(mockSetStrategyObjective).toHaveBeenCalledWith(10, "s2", "o2"));
  });
});
