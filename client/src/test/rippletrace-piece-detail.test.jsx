import { fireEvent, render, screen, waitFor } from "@testing-library/react";

/**
 * "Answers & links" on a tracked piece (ARTICLE_ANSWERS_SPEC B2 and B3): what the piece answers, as
 * stored, and how it connects to the owner's other pieces. Read only when opened. A piece not read
 * yet (an older one) offers to read it.
 */
const { mockGetDropPoints, mockEmpty, mockGetAnswers, mockGetLinks, mockQueueAnswers } = vi.hoisted(() => ({
  mockGetDropPoints: vi.fn(),
  mockEmpty: vi.fn(),
  mockGetAnswers: vi.fn(),
  mockGetLinks: vi.fn(),
  mockQueueAnswers: vi.fn(),
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
  queueShareDrafts: vi.fn(),
  getPieceAnswers: mockGetAnswers,
  getPieceLinks: mockGetLinks,
  queuePieceAnswers: mockQueueAnswers,
}));

import RippleTrace from "../components/app/RippleTrace";

const LINKS = {
  found: true,
  links_to: [{ title: "Part One", copies: [] }],
  linked_from: [{ title: "Part Three", copies: [] }, { title: "Part Four", copies: [] }],
  other_links: 3,
  unread_copies: 1,
  series: [{
    name: "Agents Series", position: 2, of: 3,
    previous: { title: "Part One", this_links_to_it: true, it_links_here: false },
    next: { title: "Part Three", this_links_to_it: false, it_links_here: true },
  }],
};

describe("RippleTrace: a piece's answers and links", () => {
  beforeEach(() => {
    mockEmpty.mockReset();
    mockEmpty.mockImplementation((value) => Promise.resolve(value));
    mockGetDropPoints.mockReset();
    mockGetDropPoints.mockResolvedValue([{
      id: "p2", title: "Part Two", platform: "DEV", url: "https://dev.to/p2", date_dropped: "2026-11-01T00:00:00",
      narrative_score: 0, velocity_score: 0, spread_score: 0, share_drafts: "made", content_hash: "h",
    }]);
    mockGetAnswers.mockReset();
    mockGetLinks.mockReset();
    mockGetLinks.mockResolvedValue(LINKS);
    mockQueueAnswers.mockReset();
    mockQueueAnswers.mockResolvedValue({ queued: true, drop_point_id: "p2" });
  });

  it("shows stored answers and how the piece connects, only when opened", async () => {
    mockGetAnswers.mockResolvedValue({
      found: true, status: "made", stale: false,
      answers: [{ question: "What is an agent?" }], raised: [{ question: "How does it remember?" }],
    });
    render(<RippleTrace />);
    fireEvent.click(await screen.findByTestId("detail-toggle-p2"));

    expect(mockGetAnswers).toHaveBeenCalledWith("p2");
    const answers = await screen.findByTestId("piece-answers");
    expect(answers).toHaveTextContent("1 answered · 1 raised, not answered");
    expect(answers).toHaveTextContent("What is an agent?");
    const links = screen.getByTestId("piece-links");
    expect(links).toHaveTextContent("Links to 1 of your pieces · linked from 2 · 3 other links");
    expect(links).toHaveTextContent("links of 1 copy unknown");
    const series = screen.getByTestId("piece-series");
    expect(series).toHaveTextContent("Agents Series: 2 of 3");
    expect(series).toHaveTextContent("Part One: linked");
    expect(series).toHaveTextContent("Part Three: not linked from here");
  });

  it("offers to read an older piece, and queues it", async () => {
    mockGetAnswers.mockResolvedValue({ found: true, status: "skipped", stale: false, answers: [], raised: [] });
    render(<RippleTrace />);
    fireEvent.click(await screen.findByTestId("detail-toggle-p2"));
    fireEvent.click(await screen.findByRole("button", { name: "Read what it answers" }));

    await waitFor(() => expect(mockQueueAnswers).toHaveBeenCalledWith("p2"));
    expect(await screen.findByText(/answers within about ten minutes/)).toBeTruthy();
  });

  it("says when the answers were read from an earlier version", async () => {
    mockGetAnswers.mockResolvedValue({
      data: { found: true, status: "made", stale: true, answers: [{ question: "Q?" }], raised: [] },
    });
    render(<RippleTrace />);
    fireEvent.click(await screen.findByTestId("detail-toggle-p2"));
    expect(await screen.findByTestId("piece-answers")).toHaveTextContent("read from an earlier version");
  });
});
