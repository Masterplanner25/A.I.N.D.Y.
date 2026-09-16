import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AppProviders } from "./utils";

// PacePanel is the client face of the pace proposal (BUILD_PLAN "Risk posture & ETA drift →
// actuation"). The server owns the tolerance, the confidence gate and what a confirmation does;
// the panel reflects the proposal and offers exactly the confirmable decision.

const { mockGetPace, mockConfirmPace, mockDismissPace } = vi.hoisted(() => ({
  mockGetPace: vi.fn(),
  mockConfirmPace: vi.fn(),
  mockDismissPace: vi.fn(),
}));

vi.mock("../api/masterplan.js", () => ({
  getPaceProposal: mockGetPace,
  confirmPace: mockConfirmPace,
  dismissPace: mockDismissPace,
}));

import PacePanel from "../components/app/PacePanel";

const EVIDENCE = {
  posture: "Aggressive", tolerance_days: 18, days_ahead_behind: -30, direction: "behind",
  exceeds_tolerance: true, eta_confidence: "high", confident: true,
  target_date: "2027-09-16T12:00:00+00:00", projected_completion_date: "2027-10-16",
  implied_posture: "Accelerated",
};
const PROPOSED = {
  proposed: true, reason: "behind_beyond_tolerance", direction: "behind", evidence: EVIDENCE, dismissed: null,
  options: [
    { decision: "retarget", kind: "refine", label: "Move the target date to the projected completion",
      consequence: { target_date_from: EVIDENCE.target_date, target_date_to: "2027-10-16", days: -30 } },
    { decision: null, kind: "revise", label: "The pace reads more like Accelerated than Aggressive", consequence: null },
  ],
};

function renderIt() {
  return render(
    <AppProviders>
      <PacePanel planId={7} />
    </AppProviders>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("PacePanel", () => {
  it("renders the proposal with the evidence and the one confirmable decision", async () => {
    mockGetPace.mockResolvedValue(PROPOSED);
    renderIt();
    await screen.findByTestId("pace-proposal");
    expect(screen.getByText(/behind its pace/)).toBeInTheDocument();
    expect(screen.getByText(/30 days behind the target/)).toBeInTheDocument();
    expect(screen.getByText(/tolerates 18 days/)).toBeInTheDocument();
    expect(screen.getByText(/RETARGET TO/)).toBeInTheDocument();
    expect(screen.getByText("NOTED")).toBeInTheDocument();
    // The implied posture is named, and explicitly not offered.
    expect(screen.getByText(/reads more like Accelerated/)).toBeInTheDocument();
    expect(screen.queryByText(/REPOSTURE/)).toBeNull();
  });

  it("confirming retargets through the API and reloads", async () => {
    mockGetPace.mockResolvedValueOnce(PROPOSED).mockResolvedValueOnce({ proposed: false, reason: "within_tolerance", evidence: { ...EVIDENCE, days_ahead_behind: 0 }, options: [] });
    mockConfirmPace.mockResolvedValue({ decision: "retarget", kind: "refine", target_date_to: "2027-10-16T00:00:00+00:00" });
    renderIt();
    await screen.findByTestId("pace-proposal");
    fireEvent.click(screen.getByText(/RETARGET TO/));
    await waitFor(() => expect(mockConfirmPace).toHaveBeenCalledWith(7, "retarget"));
    await waitFor(() => expect(screen.queryByTestId("pace-proposal")).toBeNull());
    expect(screen.getByText(/Target moved to/)).toBeInTheDocument();
    expect(mockGetPace).toHaveBeenCalledTimes(2);
  });

  it("dismissing calls the API and reloads", async () => {
    mockGetPace.mockResolvedValueOnce(PROPOSED).mockResolvedValueOnce({ ...PROPOSED, proposed: false, dismissed: { at: "2026-09-16T12:00:00Z", days_ahead_behind: -30 } });
    mockDismissPace.mockResolvedValue({ dismissed: { at: "2026-09-16T12:00:00Z", days_ahead_behind: -30 } });
    renderIt();
    await screen.findByTestId("pace-proposal");
    fireEvent.click(screen.getByText("NOTED"));
    await waitFor(() => expect(mockDismissPace).toHaveBeenCalledWith(7));
    await waitFor(() => expect(screen.queryByTestId("pace-proposal")).toBeNull());
    expect(screen.getByText(/Noted\. The proposal returns/)).toBeInTheDocument();
  });

  it("says on-pace, uncertain, or unknown instead of proposing", async () => {
    mockGetPace.mockResolvedValue({ proposed: false, reason: "low_confidence", evidence: { ...EVIDENCE, eta_confidence: "low", confident: false }, options: [] });
    renderIt();
    await screen.findByTestId("pace-panel");
    expect(screen.getByText(/Pace uncertain \(low confidence\)/)).toBeInTheDocument();
    expect(screen.queryByTestId("pace-proposal")).toBeNull();
    expect(screen.queryByText(/RETARGET/)).toBeNull();
  });
});
