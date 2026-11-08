import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { mockListDrafts, mockGetArticleAnswers, mockGetOwnLinks } = vi.hoisted(() => ({
  mockListDrafts: vi.fn(),
  mockGetArticleAnswers: vi.fn(),
  mockGetOwnLinks: vi.fn(),
}));

vi.mock("../api/search.js", () => ({
  analyzeSeo: vi.fn(),
  generateMeta: vi.fn(),
  generateTitles: vi.fn(),
  suggestSeoImprovements: vi.fn(),
  getSearchHistory: vi.fn(),
  listDrafts: mockListDrafts,
  createDraft: vi.fn(),
  getDraft: vi.fn(),
  updateDraft: vi.fn(),
  deleteDraft: vi.fn(),
  analyzeDraft: vi.fn(),
  pruneDraftAnalyses: vi.fn(),
  getArticleAnswers: mockGetArticleAnswers,
  getOwnLinks: mockGetOwnLinks,
}));

vi.mock("../components/app/SearchHistory", () => ({ default: () => null }));

import AiSeoTool from "../components/app/AiSeoTool";

/**
 * ARTICLE_ANSWERS_SPEC phase A. Usability as the owner defines it (what questions the text
 * answers) and authority as they define it (links back to their own relevant pieces). Both are
 * information for the writer: the panels show passages, never suggested wording or inserted links.
 */
describe("SEO tool: what the article answers, and links to your work", () => {
  beforeEach(() => {
    mockListDrafts.mockReset();
    mockListDrafts.mockResolvedValue({ drafts: [] });
    mockGetArticleAnswers.mockReset();
    mockGetOwnLinks.mockReset();
  });

  function typeArticle() {
    render(<AiSeoTool />);
    fireEvent.change(screen.getByPlaceholderText(/Paste your article/i), {
      target: { value: "An agent is a loop that plans, acts and checks its own results." },
    });
  }

  it("lists answers with their passages, and flags one not found word for word", async () => {
    mockGetArticleAnswers.mockResolvedValue({
      answers: [
        { question: "What is an agent?", passage: "An agent is a loop", kind: "what_is", passage_found: true },
        { question: "Is it fast?", passage: "The fastest agent ever", kind: "other", passage_found: false },
      ],
      raised: [{ question: "How does the planner remember?", passage: "", passage_found: false }],
      range: { what_is: 1, how: 0, why: 0, compared_with: 0, who: 0, other: 1 },
      reason: null,
    });
    typeArticle();
    fireEvent.click(screen.getByRole("button", { name: /What does this answer\?/i }));

    const panel = await screen.findByTestId("article-answers");
    expect(panel.textContent).toContain("What is an agent?");
    expect(panel.textContent).toContain("not found word for word");
    expect(panel.textContent).toContain("How does the planner remember?");
    expect(screen.getByTestId("answers-range").textContent).toMatch(/what is 1.*other 1/);
  });

  it("shows a failure as a failure, never as an empty list", async () => {
    mockGetArticleAnswers.mockRejectedValue(new Error("timeout"));
    typeArticle();
    fireEvent.click(screen.getByRole("button", { name: /What does this answer\?/i }));

    const panel = await screen.findByTestId("article-answers");
    expect(panel.textContent).toContain("could not be reached");
  });

  it("shows linked pieces, relevant unlinked ones with their passage, and other links", async () => {
    mockGetOwnLinks.mockResolvedValue({
      linked: [{ title: "Part One", copies: [{ platform: "DEV", url: "https://dev.to/me/one" }] }],
      missing: [{
        title: "Part Two", similarity: 0.83, passage: "Two is relevant here.",
        copies: [{ platform: "DEV", url: "https://dev.to/me/two" }, { platform: "Medium", url: "https://medium.com/@me/two" }],
      }],
      other_links: ["https://example.com/x"],
      pieces_known: 3,
      reason: null,
    });
    typeArticle();
    fireEvent.click(screen.getByRole("button", { name: /Links to my work/i }));

    const panel = await screen.findByTestId("own-links");
    await waitFor(() => expect(panel.textContent).toContain("Part Two"));
    expect(panel.textContent).toContain("Already links to (1)");
    expect(panel.textContent).toContain("Two is relevant here.");
    expect(panel.textContent).toContain("DEV, Medium");
    expect(panel.textContent).toContain("https://example.com/x");
  });
});
