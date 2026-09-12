import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const {
  mockAnalyzeSeo, mockGenerateMeta, mockGenerateTitles, mockSuggest, mockGetHistory,
  mockListDrafts, mockCreateDraft, mockGetDraft, mockUpdateDraft, mockDeleteDraft,
  mockAnalyzeDraft, mockPruneDraft,
} = vi.hoisted(() => ({
  mockAnalyzeSeo: vi.fn(),
  mockGenerateMeta: vi.fn(),
  mockGenerateTitles: vi.fn(),
  mockSuggest: vi.fn(),
  mockGetHistory: vi.fn(),
  mockListDrafts: vi.fn(),
  mockCreateDraft: vi.fn(),
  mockGetDraft: vi.fn(),
  mockUpdateDraft: vi.fn(),
  mockDeleteDraft: vi.fn(),
  mockAnalyzeDraft: vi.fn(),
  mockPruneDraft: vi.fn(),
}));

vi.mock("../api/search.js", () => ({
  analyzeSeo: mockAnalyzeSeo,
  generateMeta: mockGenerateMeta,
  generateTitles: mockGenerateTitles,
  suggestSeoImprovements: mockSuggest,
  getSearchHistory: mockGetHistory,
  listDrafts: mockListDrafts,
  createDraft: mockCreateDraft,
  getDraft: mockGetDraft,
  updateDraft: mockUpdateDraft,
  deleteDraft: mockDeleteDraft,
  analyzeDraft: mockAnalyzeDraft,
  pruneDraftAnalyses: mockPruneDraft,
}));

vi.mock("./SearchHistory", () => ({ default: () => null }));
vi.mock("../components/app/SearchHistory", () => ({ default: () => null }));

import AiSeoTool from "../components/app/AiSeoTool";

/**
 * The draft loop — SEO_EDITING_AID_SPEC §4, the last unbuilt piece of that spec.
 *
 * Everything else the tool does is a measurement taken once. Without a draft as the unit you
 * could learn that a phrase repeats and a target is thin, act on both, re-run, and the tool
 * had no memory that the first reading ever happened.
 *
 * ★ Most of what follows is about retention. The owner's call was "every analysis with a
 * prune/deletion every so often prompted by the system" — proposed, never enforced — and the
 * failure mode is quiet: a silent cap would delete the earliest analyses, which are exactly
 * what a before/after comparison is measured against.
 */
describe("SEO draft loop", () => {
  const DRAFT = {
    id: "draft-1",
    name: "Ethics and Accountability",
    content: "The body of the piece.",
    title: "Ethics and Accountability",
    target_keywords: ["runtime framework"],
    analysis_count: 3,
    latest: { id: "a3", result: { word_count: 950, readability: 58, top_keywords: [], keyword_densities: {} } },
    analyses: [{ id: "a3" }, { id: "a2" }, { id: "a1", is_baseline: true }],
    deltas: {
      available: true,
      since_previous: { word_count: 50, readability: -2, title_characters: null },
      since_baseline: { word_count: 450, readability: 18, title_characters: null },
      analyses_counted: 3,
    },
    retention: { prune_suggested: false, total: 3, threshold: 25 },
  };

  beforeEach(() => {
    for (const m of [mockAnalyzeSeo, mockGenerateMeta, mockGenerateTitles, mockSuggest,
                     mockListDrafts, mockCreateDraft, mockGetDraft, mockUpdateDraft,
                     mockAnalyzeDraft, mockPruneDraft]) {
      m.mockReset();
    }
    mockListDrafts.mockResolvedValue({
      drafts: [{ id: "draft-1", name: "Ethics and Accountability", analysis_count: 3 }],
    });
    mockGetDraft.mockResolvedValue(DRAFT);
    mockUpdateDraft.mockResolvedValue(DRAFT);
    mockAnalyzeDraft.mockResolvedValue({ analysis: DRAFT.latest.result, recorded: { id: "a4" } });
    mockCreateDraft.mockResolvedValue({ id: "draft-2", name: "New One" });
    mockPruneDraft.mockResolvedValue({ deleted: 14, refused: 0 });
  });

  const openDraft = async (id = "draft-1") => {
    fireEvent.change(await screen.findByLabelText(/^Draft$/i), { target: { value: id } });
    await waitFor(() => expect(mockGetDraft).toHaveBeenCalledWith(id));
  };

  // ── the draft is the unit ────────────────────────────────────────────────────────────

  it("lists saved drafts by the name the writer gave them", async () => {
    render(<AiSeoTool />);

    // Not "Analysis 2026-09-07 14:32" — a pile of dated scorecards is what this replaces.
    expect(await screen.findByRole("option", { name: /Ethics and Accountability/ })).toBeTruthy();
  });

  it("opening a draft restores its content, title and targets together", async () => {
    render(<AiSeoTool />);
    await openDraft();

    // ★ The targets travel with the draft. Retyping them per analysis is how two readings end
    // up measured against subtly different targets — incomparable, and silently so.
    await waitFor(() =>
      expect(screen.getByLabelText(/Target keywords/i).value).toBe("runtime framework"),
    );
    expect(screen.getByPlaceholderText(/Paste your article/i).value).toBe("The body of the piece.");
    expect(screen.getByLabelText(/^Title/i).value).toBe("Ethics and Accountability");
  });

  it("choosing 'new draft' does not clear what is already typed", async () => {
    render(<AiSeoTool />);
    fireEvent.change(screen.getByPlaceholderText(/Paste your article/i), {
      target: { value: "work in progress" },
    });
    fireEvent.change(await screen.findByLabelText(/^Draft$/i), { target: { value: "" } });

    expect(screen.getByPlaceholderText(/Paste your article/i).value).toBe("work in progress");
  });

  it("analysing a saved draft saves the current text first", async () => {
    render(<AiSeoTool />);
    await openDraft();
    fireEvent.change(screen.getByPlaceholderText(/Paste your article/i), {
      target: { value: "edited body" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Analyze & keep/i }));

    // Otherwise the reading describes the stored text, not what is on screen — and the
    // difference would show up as a delta the writer did not cause.
    await waitFor(() =>
      expect(mockUpdateDraft).toHaveBeenCalledWith("draft-1", expect.objectContaining({
        content: "edited body",
      })),
    );
    await waitFor(() => expect(mockAnalyzeDraft).toHaveBeenCalledWith("draft-1"));
  });

  // ── what moved ───────────────────────────────────────────────────────────────────────

  it("shows both what changed since last time and since the first reading", async () => {
    render(<AiSeoTool />);
    await openDraft();

    // ★ Both, deliberately. Four consecutive improvements can net to nothing, and a tool that
    // reports only "since last time" would show four wins and no progress.
    const panel = await screen.findByTestId("deltas");
    expect(panel.textContent).toMatch(/Since last analysis/);
    expect(panel.textContent).toMatch(/Since the first/);
    expect(panel.textContent).toMatch(/\+50/);
    expect(panel.textContent).toMatch(/\+450/);
  });

  it("says a metric was not measured then, rather than showing no change", async () => {
    render(<AiSeoTool />);
    await openDraft();

    // Title analysis, coverage and repetition all arrived after the first version of this
    // tool, so old rows genuinely lack them. Rendering 0 would read as "stayed the same".
    const panel = await screen.findByTestId("deltas");
    expect(panel.textContent).toMatch(/not measured then/);
  });

  it("shows nothing to compare until there are two readings", async () => {
    mockGetDraft.mockResolvedValue({
      ...DRAFT,
      deltas: { available: false, reason: "one analysis so far" },
    });
    render(<AiSeoTool />);
    await openDraft();

    await waitFor(() => expect(mockGetDraft).toHaveBeenCalled());
    expect(screen.queryByTestId("deltas")).toBeNull();
  });

  // ── ★ retention: proposed, never enforced ────────────────────────────────────────────

  it("does not mention pruning for a short history", async () => {
    render(<AiSeoTool />);
    await openDraft();

    await screen.findByTestId("deltas");
    expect(screen.queryByTestId("prune-prompt")).toBeNull();
  });

  it("raises the subject past the threshold and says what it would keep", async () => {
    mockGetDraft.mockResolvedValue({
      ...DRAFT,
      retention: {
        prune_suggested: true, total: 40, threshold: 25,
        prunable_count: 29, keeps_recent: 10, keeps_baseline: true,
        prunable_ids: ["a5", "a6"],
      },
    });
    render(<AiSeoTool />);
    await openDraft();

    const prompt = await screen.findByTestId("prune-prompt");
    expect(prompt.textContent).toMatch(/40 analyses/);
    expect(prompt.textContent).toMatch(/29 could be cleared/);
    expect(prompt.textContent).toMatch(/first reading and the most recent 10/);
  });

  it("★ deletes nothing until it is confirmed", async () => {
    mockGetDraft.mockResolvedValue({
      ...DRAFT,
      retention: {
        prune_suggested: true, total: 40, threshold: 25, prunable_count: 29,
        keeps_recent: 10, keeps_baseline: true, prunable_ids: ["a5", "a6"],
      },
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<AiSeoTool />);
    await openDraft();
    fireEvent.click(await screen.findByRole("button", { name: /Review and clear/i }));

    // Declining must leave the history intact. This is the whole reason retention here is a
    // prompt and not a cap.
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(mockPruneDraft).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("prunes exactly the ids the proposal named", async () => {
    mockGetDraft.mockResolvedValue({
      ...DRAFT,
      retention: {
        prune_suggested: true, total: 40, threshold: 25, prunable_count: 2,
        keeps_recent: 10, keeps_baseline: true, prunable_ids: ["a5", "a6"],
      },
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<AiSeoTool />);
    await openDraft();
    fireEvent.click(await screen.findByRole("button", { name: /Review and clear/i }));

    // Not a recomputed set: between the proposal and the answer a new analysis may exist, and
    // re-deriving would delete something the person was never shown.
    await waitFor(() => expect(mockPruneDraft).toHaveBeenCalledWith("draft-1", ["a5", "a6"]));
    confirm.mockRestore();
  });

  // ── saving ───────────────────────────────────────────────────────────────────────────

  it("saves a new draft under the title when there is one", async () => {
    render(<AiSeoTool />);
    fireEvent.change(screen.getByPlaceholderText(/Paste your article/i), {
      target: { value: "body" },
    });
    fireEvent.change(screen.getByLabelText(/^Title/i), { target: { value: "The Missing Layer" } });
    fireEvent.click(screen.getByRole("button", { name: /Save as draft/i }));

    await waitFor(() =>
      expect(mockCreateDraft).toHaveBeenCalledWith(
        expect.objectContaining({ name: "The Missing Layer", content: "body" }),
      ),
    );
  });

  it("does not create a nameless draft", async () => {
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("   ");
    render(<AiSeoTool />);
    fireEvent.change(screen.getByPlaceholderText(/Paste your article/i), {
      target: { value: "body" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Save as draft/i }));

    await waitFor(() => expect(prompt).toHaveBeenCalled());
    expect(mockCreateDraft).not.toHaveBeenCalled();
    prompt.mockRestore();
  });

  it("updates rather than duplicating once a draft is open", async () => {
    render(<AiSeoTool />);
    await openDraft();
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => expect(mockUpdateDraft).toHaveBeenCalled());
    expect(mockCreateDraft).not.toHaveBeenCalled();
  });
});
