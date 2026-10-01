/**
 * Drafts the agent wrote (content.draft). Owner, 2026-09-30: "where does the output go once it does
 * generate/do something?" The properties: each draft is listed with its run and sources, opens to its
 * full text, can be edited and saved, and is downloadable.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AppProviders } from "./utils";

const api = vi.hoisted(() => ({
  listDrafts: vi.fn(),
  getDraft: vi.fn(),
  updateDraft: vi.fn(),
  deleteDraft: vi.fn(),
}));

vi.mock("../api/works.js", () => api);

const DRAFT = { id: "d-1", title: "AI-Search-Optimized Marketing Plan for Nodus", run_id: "run-9", words: 812,
  created_at: "2026-09-30T19:00:00Z", sources: [{ title: "2025 ChatGPT Case Study: AI Search Optimization", kind: "own" }] };
const FULL = { ...DRAFT, body: "# AI-Search-Optimized Marketing Plan for Nodus\n\nBuild on the series [S1].\n\n## Sources\n\n- [S1] 2025 ChatGPT Case Study: AI Search Optimization" };

let DraftsSection;

beforeAll(async () => {
  DraftsSection = (await import("../components/app/DraftsSection.jsx")).default;
});

beforeEach(() => {
  vi.clearAllMocks();
  api.listDrafts.mockResolvedValue({ drafts: [DRAFT] });
  api.getDraft.mockResolvedValue(FULL);
  api.updateDraft.mockResolvedValue({ ...FULL, body: "Edited." });
});

function renderSection() {
  render(
    <AppProviders>
      <DraftsSection />
    </AppProviders>,
  );
}

describe("Drafts the agent wrote", () => {
  it("lists each draft with its sources and the run that wrote it", async () => {
    renderSection();
    expect(await screen.findByText(DRAFT.title)).toBeInTheDocument();
    expect(screen.getByText(/812 words · 1 source/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /the run that wrote it/i })).toHaveAttribute("href", "/collaborator?run=run-9");
  });

  it("opens to the full text, and saves an edit", async () => {
    renderSection();
    await userEvent.click(await screen.findByText(DRAFT.title));
    expect(await screen.findByText(/Build on the series \[S1\]/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    const box = screen.getByLabelText("Draft text");
    await userEvent.clear(box);
    await userEvent.type(box, "Edited.");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledWith("d-1", { body: "Edited." }));
  });

  it("shows nothing when there are no drafts", async () => {
    api.listDrafts.mockResolvedValue({ drafts: [] });
    renderSection();
    await waitFor(() => expect(api.listDrafts).toHaveBeenCalled());
    expect(screen.queryByText(/Drafts the agent wrote/)).not.toBeInTheDocument();
  });
});
