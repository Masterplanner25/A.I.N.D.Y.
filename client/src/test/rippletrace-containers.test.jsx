import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const {
  mockGetContentSources, mockGetDropPoints, mockIngest, mockPoll, mockSetActive,
  mockDeleteSource, mockDetect, mockDetectOne,
  mockGetCandidates, mockGetPerformance, mockConfirm, mockDismiss,
} = vi.hoisted(() => ({
  mockGetContentSources: vi.fn(),
  mockGetDropPoints: vi.fn(),
  mockIngest: vi.fn(),
  mockPoll: vi.fn(),
  mockSetActive: vi.fn(),
  mockDeleteSource: vi.fn(),
  mockDetect: vi.fn(),
  mockDetectOne: vi.fn(),
  mockGetCandidates: vi.fn(),
  mockGetPerformance: vi.fn(),
  mockConfirm: vi.fn(),
  mockDismiss: vi.fn(),
}));

vi.mock("../api/rippletrace.js", () => ({
  getContentSources: mockGetContentSources,
  getRippleDropPoints: mockGetDropPoints,
  ingestContentUrl: mockIngest,
  pollContentSource: mockPoll,
  setContentSourceActive: mockSetActive,
  deleteContentSource: mockDeleteSource,
  detectRipples: mockDetect,
  detectRipplesForDropPoint: mockDetectOne,
  getContainerCandidates: mockGetCandidates,
  getContainerPerformance: mockGetPerformance,
  confirmContainer: mockConfirm,
  dismissContainer: mockDismiss,
}));

import RippleTrace from "../components/app/RippleTrace";

/**
 * Containers — TITLE_AS_CONTAINER_SPEC §4b. The owner's call was **confirmed, not inferred**.
 *
 * ★ The corpus can measure that four words recur across a catalogue. It cannot say that
 * "2025 ChatGPT Case Study Series" is a work someone made — and three engines (influence
 * graph, causality, strategies) reason from `tagged_entities` as though it were a fact about
 * the author's body of work. So the surface below asks, and nothing is written until it is
 * answered.
 */
describe("RippleTrace containers", () => {
  const CANDIDATE = {
    name: "2025 ChatGPT Case Study Series",
    normalized: "2025 chatgpt case study series",
    drop_count: 46,
    corpus_size: 215,
    share: 21.4,
    examples: [
      "2025 ChatGPT Case Study Series: Ethics and Accountability",
      "2025 ChatGPT Case Study Series: Prompt Engineering",
    ],
  };

  const CONTAINER = {
    id: "c-1",
    name: "2025 ChatGPT Case Study Series",
    status: "confirmed",
    performance: {
      drops: 46, pings: 87, avg_narrative: 32.4, cadence_days: 2.8,
      trajectory: { available: true, early_avg: 18.2, late_avg: 46.6, change: 28.4 },
    },
  };

  beforeEach(() => {
    for (const m of [mockGetContentSources, mockGetDropPoints, mockGetCandidates,
                     mockGetPerformance, mockConfirm, mockDismiss]) {
      m.mockReset();
    }
    mockGetContentSources.mockResolvedValue({ sources: [] });
    mockGetDropPoints.mockResolvedValue([]);
    mockGetCandidates.mockResolvedValue({ candidates: [CANDIDATE] });
    mockGetPerformance.mockResolvedValue({ containers: [] });
    mockConfirm.mockResolvedValue({ id: "c-1", drop_count: 46 });
    mockDismiss.mockResolvedValue({ id: "c-1", status: "dismissed" });
  });

  // ── it asks ──────────────────────────────────────────────────────────────────────────

  it("asks whether a recurring phrase is a series", async () => {
    render(<RippleTrace />);

    const panel = await screen.findByTestId("container-candidates");
    expect(panel.textContent).toMatch(/Is this a series of yours\?/);
    expect(panel.textContent).toMatch(/2025 ChatGPT Case Study Series/);
  });

  it("shows the evidence, not just a percentage", async () => {
    render(<RippleTrace />);

    // "Is this a series of yours?" needs the titles far more than it needs a number.
    const panel = await screen.findByTestId("container-candidates");
    expect(panel.textContent).toMatch(/46 of 215 pieces \(21.4%\)/);
    expect(panel.textContent).toMatch(/Ethics and Accountability/);
    expect(panel.textContent).toMatch(/Prompt Engineering/);
  });

  it("★ loading the page tags nothing", async () => {
    render(<RippleTrace />);
    await screen.findByTestId("container-candidates");

    // Fetching candidates measures; it does not write. Confirming is the only thing that
    // links pieces together, and that requires a click.
    expect(mockConfirm).not.toHaveBeenCalled();
    expect(mockDismiss).not.toHaveBeenCalled();
  });

  it("says nothing when the corpus has no repeated structure", async () => {
    // The keyword-style author, handled by the same rule for free — no container is the
    // correct answer, not a failure.
    mockGetCandidates.mockResolvedValue({ candidates: [] });
    render(<RippleTrace />);

    await waitFor(() => expect(mockGetCandidates).toHaveBeenCalled());
    expect(screen.queryByTestId("container-candidates")).toBeNull();
  });

  // ── the two answers ──────────────────────────────────────────────────────────────────

  it("confirming sends the name the author wrote", async () => {
    render(<RippleTrace />);
    await screen.findByTestId("container-candidates");
    fireEvent.click(screen.getByRole("button", { name: /Yes, this is mine/i }));

    await waitFor(() =>
      expect(mockConfirm).toHaveBeenCalledWith("2025 ChatGPT Case Study Series"),
    );
  });

  it("dismissing records the answer rather than just hiding it", async () => {
    render(<RippleTrace />);
    await screen.findByTestId("container-candidates");
    fireEvent.click(screen.getByRole("button", { name: /Not a series/i }));

    // Without a recorded dismissal the system re-proposes a rejected candidate on every
    // visit, which turns an answered question into a nag.
    await waitFor(() =>
      expect(mockDismiss).toHaveBeenCalledWith("2025 ChatGPT Case Study Series"),
    );
  });

  it("reloads after a decision so the question stops being asked", async () => {
    render(<RippleTrace />);
    await screen.findByTestId("container-candidates");
    fireEvent.click(screen.getByRole("button", { name: /Yes, this is mine/i }));

    await waitFor(() => expect(mockGetCandidates).toHaveBeenCalledTimes(2));
  });

  // ── what a confirmed series then shows ───────────────────────────────────────────────

  it("reports what the series has actually done", async () => {
    mockGetPerformance.mockResolvedValue({ containers: [CONTAINER] });
    render(<RippleTrace />);

    const panel = await screen.findByTestId("containers");
    expect(panel.textContent).toMatch(/46 pieces/);
    expect(panel.textContent).toMatch(/87 echoes/);
    expect(panel.textContent).toMatch(/avg narrative 32.4/);
    expect(panel.textContent).toMatch(/every 2.8 days/);
  });

  it("shows both halves of the trajectory, not just the change", async () => {
    mockGetPerformance.mockResolvedValue({ containers: [CONTAINER] });
    render(<RippleTrace />);

    // ★ "+28.4" says nothing about whether the series started at 3 or at 40.
    const trajectory = await screen.findByTestId("container-trajectory");
    expect(trajectory.textContent).toMatch(/18.2 → 46.6/);
  });

  it("omits the trajectory on a series too short to have one", async () => {
    mockGetPerformance.mockResolvedValue({
      containers: [{
        ...CONTAINER,
        performance: {
          ...CONTAINER.performance,
          trajectory: { available: false, reason: "needs at least 6 dated pieces" },
        },
      }],
    });
    render(<RippleTrace />);

    await screen.findByTestId("containers");
    expect(screen.queryByTestId("container-trajectory")).toBeNull();
  });

  it("a container endpoint failure does not break the page", async () => {
    // These are additive panels on a surface that already worked; a new feature failing must
    // not take the tracked-content view with it.
    mockGetCandidates.mockRejectedValue(new Error("not deployed yet"));
    mockGetPerformance.mockRejectedValue(new Error("not deployed yet"));
    render(<RippleTrace />);

    expect(await screen.findByText(/Add published content/i)).toBeTruthy();
    expect(screen.queryByTestId("container-candidates")).toBeNull();
  });
});
