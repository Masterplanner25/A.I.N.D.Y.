import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { mockAnalyzeSeo, mockGenerateMeta, mockGenerateTitles, mockSuggest, mockGetHistory } =
  vi.hoisted(() => ({
    mockAnalyzeSeo: vi.fn(),
    mockGenerateMeta: vi.fn(),
    mockGenerateTitles: vi.fn(),
    mockSuggest: vi.fn(),
    mockGetHistory: vi.fn(),
  }));

vi.mock("../api/search.js", () => ({
  analyzeSeo: mockAnalyzeSeo,
  generateMeta: mockGenerateMeta,
  generateTitles: mockGenerateTitles,
  suggestSeoImprovements: mockSuggest,
  getSearchHistory: mockGetHistory,
}));

vi.mock("./SearchHistory", () => ({ default: () => null }));
vi.mock("../components/app/SearchHistory", () => ({ default: () => null }));

import AiSeoTool from "../components/app/AiSeoTool";

/**
 * The SEO tool had no concept of a title. `seo_analysis` took one blob of body text and
 * there was no title parameter anywhere, so the tool could report on a draft without ever
 * looking at the line a search result actually shows — and the only budget it enforced, the
 * meta description's, was never displayed to the writer at all
 * (TITLE_AS_CONTAINER_SPEC §6, §6a).
 *
 * ★ The button is the sharpest of these. It read "Generate Meta" and returned a
 * ~160-character sentence, which is a title generator to anyone who has not read the code —
 * and a title budget is ~60 characters, not ~160. Being wrong there is expensive in a way
 * that a mislabelled panel further down the page is not.
 */
describe("SEO tool title and character budgets", () => {
  beforeEach(() => {
    mockAnalyzeSeo.mockReset();
    mockGenerateMeta.mockReset();
    mockSuggest.mockReset();
    mockAnalyzeSeo.mockResolvedValue({
      word_count: 900,
      readability: 55,
      top_keywords: ["frameworks"],
      keyword_densities: { frameworks: 1.2 },
      title_analysis: {
        title: "2025 ChatGPT Case Study Series: Ethics and Accountability",
        characters: 67,
        budget: 60,
        over_by: 7,
        verdict: "long",
        truncated: true,
        serp_preview: "2025 ChatGPT Case Study Series: Ethics and…",
      },
    });
    mockGenerateMeta.mockResolvedValue({
      meta_description: "A summary of the piece.",
      characters: 23,
      budget: 160,
    });
    mockGenerateTitles.mockReset();
    mockGenerateTitles.mockResolvedValue({
      candidates: [
        { title: "How frameworks shape a runtime", characters: 29, budget: 60, over_by: 0 },
        { title: "A longer option that runs past the budget line", characters: 46, budget: 60, over_by: 0 },
      ],
      count: 2,
      budget: 60,
      current_title: "",
      reason: null,
    });
  });

  const typeBody = (text = "some article body") =>
    fireEvent.change(screen.getByPlaceholderText(/Paste your article/i), {
      target: { value: text },
    });

  const typeTitle = (text) =>
    fireEvent.change(screen.getByLabelText(/Title/i), { target: { value: text } });

  // ── the button says what it produces ─────────────────────────────────────────────────

  it("names the meta description on the button, not just in the result panel", () => {
    render(<AiSeoTool />);

    // "Generate Meta" read as a title generator. A title budget is ~60 characters; this
    // returns ~160, and the difference only surfaced once someone read the code.
    expect(screen.getByRole("button", { name: /Generate Meta Description/i })).toBeTruthy();
  });

  // ── the title, and its budget ────────────────────────────────────────────────────────

  it("offers a title field and marks it optional", () => {
    render(<AiSeoTool />);

    // Optional on purpose: analysing a body of text with no title is a legitimate use, and
    // the tool must not nag for a field the writer left empty.
    expect(screen.getByLabelText(/Title/i)).toBeTruthy();
    expect(screen.getByText(/\(optional\)/i)).toBeTruthy();
  });

  it("counts title characters as they are typed", () => {
    render(<AiSeoTool />);
    typeTitle("A concise headline");

    expect(screen.getByTestId("title-character-count").textContent)
      .toMatch(/18 \/ 60 characters/);
  });

  it("shows no counter before anything is typed", () => {
    render(<AiSeoTool />);
    expect(screen.queryByTestId("title-character-count")).toBeNull();
  });

  it("sends the title with the analysis", async () => {
    render(<AiSeoTool />);
    typeBody("some article body");
    typeTitle("A concise headline");
    fireEvent.click(screen.getByRole("button", { name: /Analyze SEO/i }));

    await waitFor(() =>
      expect(mockAnalyzeSeo).toHaveBeenCalledWith("some article body", "A concise headline"),
    );
  });

  it("omits the title when it is blank, so the request is unchanged", async () => {
    render(<AiSeoTool />);
    typeBody("some article body");
    fireEvent.click(screen.getByRole("button", { name: /Analyze SEO/i }));

    await waitFor(() => expect(mockAnalyzeSeo).toHaveBeenCalledWith("some article body", ""));
  });

  // ── the verdict never arrives without its number ─────────────────────────────────────

  it("reports the count and the budget, not just a verdict", async () => {
    render(<AiSeoTool />);
    typeBody();
    fireEvent.click(screen.getByRole("button", { name: /Analyze SEO/i }));

    // ★ A budget that hides the measurement is the tool deciding for the writer.
    const panel = await screen.findByTestId("title-analysis");
    expect(panel.textContent).toMatch(/67 characters/);
    expect(panel.textContent).toMatch(/\/ 60/);
    expect(panel.textContent).toMatch(/7 over/);
  });

  it("shows what survives truncation rather than describing it", async () => {
    render(<AiSeoTool />);
    typeBody();
    fireEvent.click(screen.getByRole("button", { name: /Analyze SEO/i }));

    // "67 characters, budget 60" says they are over. Seeing which words fall off the end is
    // what tells them where to cut.
    const panel = await screen.findByTestId("title-analysis");
    expect(panel.textContent).toContain("2025 ChatGPT Case Study Series: Ethics and…");
  });

  it("shows no title panel when the analysis carries none", async () => {
    mockAnalyzeSeo.mockResolvedValue({
      word_count: 900, readability: 55, top_keywords: [], keyword_densities: {},
    });
    render(<AiSeoTool />);
    typeBody();
    fireEvent.click(screen.getByRole("button", { name: /Analyze SEO/i }));

    await screen.findByText(/Word Count/i);
    expect(screen.queryByTestId("title-analysis")).toBeNull();
  });

  // ── the live word count ──────────────────────────────────────────────────────────────

  it("counts body words while they are being written", () => {
    render(<AiSeoTool />);
    typeBody("one two three four five");

    // The count previously appeared only after Analyze was clicked — a count you have to ask
    // for is not much use while you are still writing.
    expect(screen.getByTestId("live-word-count").textContent).toMatch(/5 words/);
  });

  it("does not count punctuation as words", () => {
    render(<AiSeoTool />);
    typeBody("Hello, world. This is a test!");

    // Matches the server's regex tokenizer. NLTK's word_tokenize emits "," and "." as tokens,
    // which is why the server's count depends on whether an optional corpus is installed —
    // the client must not reproduce that ambiguity.
    expect(screen.getByTestId("live-word-count").textContent).toMatch(/6 words/);
  });

  // ── the meta description's own budget ────────────────────────────────────────────────

  it("shows the meta description's character count against its budget", async () => {
    render(<AiSeoTool />);
    typeBody();
    fireEvent.click(screen.getByRole("button", { name: /Generate Meta Description/i }));

    const count = await screen.findByTestId("meta-character-count");
    expect(count.textContent).toMatch(/23 characters/);
    expect(count.textContent).toMatch(/160/);
  });

  it("omits the count when the server did not send one", async () => {
    mockGenerateMeta.mockResolvedValue({ meta_description: "A summary." });
    render(<AiSeoTool />);
    typeBody();
    fireEvent.click(screen.getByRole("button", { name: /Generate Meta Description/i }));

    await screen.findByText(/"A summary."/);
    expect(screen.queryByTestId("meta-character-count")).toBeNull();
  });

  // ── title generation: it proposes, it never replaces ─────────────────────────────────

  it("offers a title suggestion action", () => {
    render(<AiSeoTool />);
    expect(screen.getByRole("button", { name: /Suggest Titles/i })).toBeTruthy();
  });

  it("sends the article and the writer's own title as context", async () => {
    render(<AiSeoTool />);
    typeBody("some article body");
    typeTitle("Series: Part Four");
    fireEvent.click(screen.getByRole("button", { name: /Suggest Titles/i }));

    await waitFor(() =>
      expect(mockGenerateTitles).toHaveBeenCalledWith("some article body", "Series: Part Four"),
    );
  });

  it("lists options with their measurements", async () => {
    render(<AiSeoTool />);
    typeBody();
    fireEvent.click(screen.getByRole("button", { name: /Suggest Titles/i }));

    const panel = await screen.findByTestId("title-options");
    expect(panel.textContent).toContain("How frameworks shape a runtime");
    expect(panel.textContent).toMatch(/29 \/ 60 characters/);
  });

  it("★ never replaces the writer's title", async () => {
    render(<AiSeoTool />);
    typeBody();
    typeTitle("My own headline");
    fireEvent.click(screen.getByRole("button", { name: /Suggest Titles/i }));
    await screen.findByTestId("title-options");

    // No apply/use button, and the field still holds what the writer typed. A tool that swaps
    // the author's title for its own has stopped being an editing aid.
    expect(screen.queryByRole("button", { name: /^(Apply|Use this|Replace)/i })).toBeNull();
    expect(screen.getByLabelText(/Title/i).value).toBe("My own headline");
  });

  it("says why when there are no suggestions, rather than inventing one", async () => {
    mockGenerateTitles.mockResolvedValue({
      candidates: [],
      count: 0,
      reason: "the title service is temporarily unavailable",
    });
    render(<AiSeoTool />);
    typeBody();
    fireEvent.click(screen.getByRole("button", { name: /Suggest Titles/i }));

    const reason = await screen.findByTestId("title-options-reason");
    expect(reason.textContent).toMatch(/temporarily unavailable/);
  });

  it("a failed request reports the failure instead of falling back", async () => {
    mockGenerateTitles.mockRejectedValue(new Error("network down"));
    render(<AiSeoTool />);
    typeBody("Frameworks and relationships shape a runtime.");
    fireEvent.click(screen.getByRole("button", { name: /Suggest Titles/i }));

    // ★ A locally-assembled title would look exactly like a suggestion. Silence is honest.
    const reason = await screen.findByTestId("title-options-reason");
    expect(reason.textContent).toMatch(/could not be reached/);
    expect(reason.textContent).not.toMatch(/Frameworks/);
  });
});
