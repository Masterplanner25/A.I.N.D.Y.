import { fireEvent, render, screen, waitFor } from "@testing-library/react";

/**
 * Share drafts on RippleTrace (owner, 2026-10-25). A new piece gets them on its own; the page says
 * where they are, and an older piece (`skipped`) has a button to ask for them. A copy of a
 * cross-post has none of its own, and a piece with no text (a video) says nothing.
 */
const { mockGetDropPoints, mockQueue, mockEmpty } = vi.hoisted(() => ({
  mockGetDropPoints: vi.fn(),
  mockQueue: vi.fn(),
  mockEmpty: vi.fn(),
}));

vi.mock("../api/rippletrace.js", () => ({
  getContentSources: () => mockEmpty({ sources: [] }),
  getRippleDropPoints: mockGetDropPoints,
  ingestContentUrl: vi.fn(),
  pollContentSource: vi.fn(),
  setContentSourceActive: vi.fn(),
  deleteContentSource: vi.fn(),
  detectRipples: vi.fn(),
  detectRipplesForDropPoint: vi.fn(),
  getContainerCandidates: () => mockEmpty({ candidates: [] }),
  getContainerPerformance: () => mockEmpty({ containers: [] }),
  confirmContainer: vi.fn(),
  dismissContainer: vi.fn(),
  recordCitation: vi.fn(),
  queueShareDrafts: mockQueue,
}));

import RippleTrace from "../components/app/RippleTrace";

const piece = (id, share_drafts, content_hash = "h") => ({
  id, title: `Piece ${id}`, platform: "DEV", url: `https://dev.to/${id}`, date_dropped: "2026-10-20T00:00:00",
  narrative_score: 0, velocity_score: 0, spread_score: 0, share_drafts, content_hash,
});

describe("RippleTrace share drafts", () => {
  beforeEach(() => {
    mockEmpty.mockReset();
    mockEmpty.mockImplementation((value) => Promise.resolve(value));
    mockQueue.mockReset();
    mockQueue.mockResolvedValue({ queued: true, drop_point_id: "old" });
    mockGetDropPoints.mockReset();
    mockGetDropPoints.mockResolvedValue([
      piece("new", null),
      piece("made", "made"),
      piece("old", "skipped"),
      piece("copy", "cross_post"),
      piece("video", null, null),
    ]);
  });

  it("says where each piece's share drafts are", async () => {
    render(<RippleTrace />);
    expect(await screen.findByTestId("share-status-new")).toHaveTextContent("being written");
    expect(screen.getByTestId("share-status-made")).toHaveTextContent("in Drafts on the Work page");
    expect(screen.getByTestId("share-status-copy")).toHaveTextContent("with the earliest copy");
    expect(screen.queryByTestId("share-status-old")).toBeNull();
    expect(screen.queryByTestId("share-status-video")).toBeNull();
  });

  it("offers drafts for an older piece and queues them", async () => {
    render(<RippleTrace />);
    const ask = await screen.findByRole("button", { name: "Make share drafts" });
    expect(screen.getAllByRole("button", { name: "Make share drafts" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Share drafts again" })).toBeTruthy();

    fireEvent.click(ask);
    await waitFor(() => expect(mockQueue).toHaveBeenCalledWith("old"));
    expect(await screen.findByText(/within about ten minutes/)).toBeTruthy();
  });
});
