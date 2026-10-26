/**
 * Drafts the agent wrote (content.draft). Owner, 2026-09-30: "where does the output go once it does
 * generate/do something?" The properties: each draft is listed with its run and sources, opens to its
 * full text, can be edited and saved, and is downloadable. Each card names its Work, marks the newest
 * draft for that Work, and can be deleted without opening it.
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

  it("says which Work each draft is about and which is the newest for it", async () => {
    // Owner, 2026-10-25: four drafts about Nodus and no way to tell which one to use.
    api.listDrafts.mockResolvedValue({ drafts: [
      { ...DRAFT, id: "d-2", title: "Nodus — Canonical Entity Reference", work_name: "Nodus", newest_for_work: true },
      { ...DRAFT, id: "d-1", work_name: "Nodus", newest_for_work: false },
    ] });
    renderSection();
    expect(await screen.findByText("newest for Nodus")).toBeInTheDocument();
    expect(screen.getByText("older: a newer draft about Nodus exists")).toBeInTheDocument();
  });

  it("deletes from the card without opening the draft, only after confirming", async () => {
    api.deleteDraft.mockResolvedValue({});
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderSection();
    const remove = await screen.findByRole("button", { name: `Delete ${DRAFT.title}` });
    await userEvent.click(remove);
    expect(api.deleteDraft).not.toHaveBeenCalled();
    await userEvent.click(remove);
    await waitFor(() => expect(api.deleteDraft).toHaveBeenCalledWith("d-1"));
    expect(api.getDraft).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("labels a share draft with its kind, the piece it came from, and how the piece was read", async () => {
    api.listDrafts.mockResolvedValue({ drafts: [{
      id: "s-1", title: "LinkedIn post: What a version promises", words: 140, kind: "linkedin_post",
      drop_point_id: "dp-1", brief: "Read as: A version number is a promise the release has to keep.",
      created_at: "2026-10-25T19:00:00Z",
      sources: [{ title: "What a version promises", url: "https://dev.to/x", platform: "DEV", kind: "own" }],
    }] });
    renderSection();
    const label = await screen.findByTestId("share-draft-label");
    expect(label).toHaveTextContent("LinkedIn post · from What a version promises");
    expect(label).toHaveTextContent("Read as: A version number is a promise the release has to keep.");
  });

  it("shows no share label on a document", async () => {
    renderSection();
    await screen.findByText(DRAFT.title);
    expect(screen.queryByTestId("share-draft-label")).not.toBeInTheDocument();
  });

  it("shows nothing when there are no drafts", async () => {
    api.listDrafts.mockResolvedValue({ drafts: [] });
    renderSection();
    await waitFor(() => expect(api.listDrafts).toHaveBeenCalled());
    expect(screen.queryByText(/Drafts the agent wrote/)).not.toBeInTheDocument();
  });
});
