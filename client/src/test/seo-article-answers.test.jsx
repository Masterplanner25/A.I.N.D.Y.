import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { mockListDrafts, mockGetArticleAnswers, mockGetOwnLinks, mockGetArticleClaims, mockGetStructure, mockGetStructurePatterns } = vi.hoisted(() => ({
  mockGetStructure: vi.fn(),
  mockGetStructurePatterns: vi.fn(),
  mockGetArticleClaims: vi.fn(),
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
  getArticleClaims: mockGetArticleClaims,
  getStructure: mockGetStructure,
  getStructurePatterns: mockGetStructurePatterns,
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

/**
 * ARTICLE_ANSWERS_SPEC phase D1: What does this claim? Information only. A claim that says what the writer
 * denied is shown as such, never blocked; the rest shows what it leans on, not whether it is true.
 */
describe("SEO tool: what the draft claims", () => {
  beforeEach(() => {
    mockListDrafts.mockReset();
    mockListDrafts.mockResolvedValue({ drafts: [] });
    mockGetArticleClaims.mockReset();
  });

  function typeDraft() {
    render(<AiSeoTool />);
    fireEvent.change(screen.getByPlaceholderText(/Paste your article/i), {
      target: { value: "Nodus is part of A.I.N.D.Y. Gartner found that 40% of agent projects fail." },
    });
  }

  it("shows each claim with its status, what it matches or contradicts, and the draft's links", async () => {
    mockGetArticleClaims.mockResolvedValue({
      claims: [
        { claim: "Nodus is part of A.I.N.D.Y.", kind: "named", found: true, work: "Nodus", status: "contradicts",
          fact: null, denied: "Nodus is part of A.I.N.D.Y.", source: null },
        { claim: "Gartner found that 40% of agent projects fail", kind: "attribution", found: true, work: null,
          status: "sourced", fact: null, denied: null, source: "https://gartner.example/agents" },
        { claim: "It ships with forty plugins", kind: "number", found: false, work: null, status: "unsourced",
          fact: null, denied: null, source: null },
      ],
      counts: { contradicts: 1, confirmed: 0, new: 0, sourced: 1, unsourced: 1 },
      sources: [{ url: "https://gartner.example/agents", own: false, claims: [1] }],
      reason: null,
    });
    typeDraft();
    fireEvent.click(screen.getByRole("button", { name: /What does this claim\?/i }));

    const panel = await screen.findByTestId("article-claims");
    expect(panel).toHaveTextContent("says what you denied · Nodus");
    expect(panel).toHaveTextContent("You denied: Nodus is part of A.I.N.D.Y.");
    expect(panel).toHaveTextContent("Source: https://gartner.example/agents");
    expect(panel).toHaveTextContent("no source in the draft");
    expect(panel).toHaveTextContent("(not found word for word in the text)");
    expect(screen.getByTestId("claims-counts")).toHaveTextContent("says what you denied 1 · sourced 1 · no source in the draft 1");
    expect(panel).toHaveTextContent("1 claim leans on it");
  });

  it("shows the server's sentence when the writer has no key", async () => {
    const err = Object.assign(new Error("API Error (402)"), {
      status: 402,
      data: JSON.stringify({ detail: "This needs your own OpenAI API key. Add it in Settings." }),
    });
    mockGetArticleClaims.mockRejectedValue(err);
    typeDraft();
    fireEvent.click(screen.getByRole("button", { name: /What does this claim\?/i }));
    await waitFor(() =>
      expect(screen.getByTestId("article-claims")).toHaveTextContent(
        "No claims listed: This needs your own OpenAI API key. Add it in Settings.",
      ),
    );
  });
});

/**
 * ARTICLE_ANSWERS_SPEC phase D2: What's the structure? It reveals that there is a structure: the patterns named with
 * every instance, and the shape the series shares beside the draft. Never a score.
 */
describe("SEO tool: the draft's structure", () => {
  const STRUCTURE = (seriesName) => ({
    skeleton: { sections: [{ heading: "What's Next?", words: 120, share: 100 }], words: 120, paragraphs: 3,
                opening: "Opening line.", closing: "Closing line.", closing_heading: "What's Next?" },
    openings: [],
    repeats: { phrases: [], single_word_openers: [], overused_words: [] },
    series: {
      name: seriesName,
      options: ["2026 Agents Case Study Series", "2025 ChatGPT Case Study Series"],
      titles: [],
      shape: seriesName ? {
        pieces: 12, median_words: 2400, median_sections: 14,
        headings: [{ heading: "What's Next?", pieces: 11, in_draft: true },
                   { heading: "Explore the Projects", pieces: 9, in_draft: false }],
        closing_heading: { heading: "Previous Work", pieces: 10, in_draft: false },
        openings: [], closings: [{ starts: "article N i", pieces: 8, example: "Article 1 — I Created" }],
      } : null,
    },
  });

  beforeEach(() => {
    mockListDrafts.mockReset();
    mockListDrafts.mockResolvedValue({ drafts: [] });
    mockGetStructure.mockReset();
    mockGetStructurePatterns.mockReset();
  });

  function typeDraft() {
    render(<AiSeoTool />);
    fireEvent.change(screen.getByPlaceholderText(/Paste your article/i), {
      target: { value: "It could inspect. It could search. It could run." },
    });
  }

  it("names the patterns with every instance, and shows the series' shape beside the draft", async () => {
    mockGetStructurePatterns.mockResolvedValue({
      patterns: [{ name: "the 'It could' run", kind: "list",
                   instances: ["It could inspect.", "It could search.", "It could run.", "It could stop."] }],
      reason: null,
    });
    mockGetStructure.mockResolvedValue(STRUCTURE("2026 Agents Case Study Series"));
    typeDraft();
    fireEvent.click(screen.getByRole("button", { name: /What's the structure\?/i }));

    const patterns = await screen.findByTestId("structure-patterns");
    expect(patterns).toHaveTextContent("list");
    expect(patterns).toHaveTextContent("the 'It could' run");
    expect(patterns).toHaveTextContent("and 1 more");
    fireEvent.click(screen.getByRole("button", { name: "and 1 more" }));
    expect(patterns).toHaveTextContent("It could stop.");

    const series = await screen.findByTestId("structure-series");
    expect(series).toHaveTextContent("12 published pieces");
    expect(series).toHaveTextContent("What's Next? in 11 of 12 · in this draft");
    expect(series).toHaveTextContent("Explore the Projects in 9 of 12 · not in this draft");
    expect(series).toHaveTextContent("They close on Previous Work (10 of 12) · this draft doesn't");
    expect(screen.getByTestId("structure").textContent).not.toMatch(/score|grade/i);
  });

  it("asks for a series when the title names none, and reloads with the one picked", async () => {
    mockGetStructurePatterns.mockResolvedValue({ patterns: [], reason: "no patterns with two instances in the text were returned" });
    mockGetStructure.mockResolvedValueOnce(STRUCTURE(null)).mockResolvedValueOnce(STRUCTURE("2025 ChatGPT Case Study Series"));
    typeDraft();
    fireEvent.click(screen.getByRole("button", { name: /What's the structure\?/i }));

    const series = await screen.findByTestId("structure-series");
    expect(series).toHaveTextContent("Pick one to see its shape");
    expect(screen.getByTestId("structure-patterns")).toHaveTextContent("No patterns named");
    fireEvent.change(screen.getByLabelText("Series"), { target: { value: "2025 ChatGPT Case Study Series" } });
    await waitFor(() => expect(mockGetStructure).toHaveBeenLastCalledWith(
      "It could inspect. It could search. It could run.", "", "2025 ChatGPT Case Study Series"));
    await waitFor(() => expect(screen.getByTestId("structure-series")).toHaveTextContent("12 published pieces"));
  });
});

