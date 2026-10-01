/**
 * Collaborator's Work mode (WORK_MODEL_SPEC §4, §6). The properties that matter: a proposal is
 * confirmed in the owner's words (never without a summary), "Not mine" dismisses it, confirmed
 * works show how they relate and what they serve, and the owner can read exactly what the agent
 * is told.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AppProviders } from "./utils";

const api = vi.hoisted(() => ({
  listWorks: vi.fn(),
  listWorkProposals: vi.fn(),
  confirmWorkProposal: vi.fn(),
  dismissWorkProposal: vi.fn(),
  createWork: vi.fn(),
  updateWork: vi.fn(),
  deleteWork: vi.fn(),
  addWorkLink: vi.fn(),
  removeWorkLink: vi.fn(),
  setWorkObjectives: vi.fn(),
  getPublishedWriting: vi.fn(),
  storePublishedWriting: vi.fn(),
  listDrafts: vi.fn(),
  getDraft: vi.fn(),
  updateDraft: vi.fn(),
  deleteDraft: vi.fn(),
  addPresence: vi.fn(),
  removePresence: vi.fn(),
  getResolution: vi.fn(),
  startResolution: vi.fn(),
}));

vi.mock("../api/works.js", () => api);

const VOCAB = {
  kinds: ["project", "product", "series", "practice", "publication", "other"],
  roles: ["creator", "author", "maintainer", "contributor"],
  statuses: ["active", "finished", "paused", "planned"],
  relations: { built_on: "runs on / depends on", executes: "is the language or engine that runs" },
};
const RUNTIME = { id: "w-rt", name: "aindy-runtime", kind: "project", role: "creator", status: "active",
  summary: "Self-hosted runtime for AI agents.", objectives: [{ id: "o-1", name: "Platform Enablement" }] };
const NODUS = { id: "w-nd", name: "Nodus", kind: "project", role: "creator", status: "active",
  summary: "The orchestration language.", objectives: [] };
const AISO = { id: "w-ai", name: "AI Search Optimization", kind: "practice", role: "creator", status: "active",
  summary: "Knowledge, entity and semantic optimization.", objectives: [],
  success_criteria: "Resolution, not rankings: does a direct search bring back the right entity?" };
const PROPOSAL = { key: "container:c-1", source: "container", name: "2025 ChatGPT Case Study Series",
  summary: "", kind: "series", role: "author", status: "active", container_id: "c-1",
  question: "You confirmed '2025 ChatGPT Case Study Series' as a series of yours. What was it for?",
  evidence: "Confirmed in RippleTrace, 42 pieces at the time" };

let WorkPanel;

beforeAll(async () => {
  WorkPanel = (await import("../components/app/WorkPanel.jsx")).default;
});

beforeEach(() => {
  vi.clearAllMocks();
  api.listWorks.mockResolvedValue({
    works: [RUNTIME, NODUS, AISO],
    links: [{ id: "l-1", from_work_id: "w-rt", to_work_id: "w-nd", relation: "executes", note: null }],
    objectives_available: [{ id: "o-1", name: "Platform Enablement" }, { id: "o-2", name: "Ethical AI Framework" }],
    vocabulary: VOCAB,
    agent_block: "## The user's work\n- aindy-runtime (project, creator, active): Self-hosted runtime for AI agents.; executes Nodus",
  });
  api.listWorkProposals.mockResolvedValue({ proposals: [PROPOSAL] });
  api.getPublishedWriting.mockResolvedValue({
    pieces: 214, stored: 60, recallable: 40, no_text: 15, pending: 139,
    platforms: { DEV: { pieces: 143, recallable: 30, no_text: 0 }, YouTube: { pieces: 15, recallable: 0, no_text: 15 } },
  });
  api.listDrafts.mockResolvedValue({ drafts: [] });
  api.getResolution.mockResolvedValue({ latest: null, self_descriptions: [], entities: {} });
  api.addPresence.mockResolvedValue({});
  api.storePublishedWriting.mockResolvedValue({ status: { pieces: 214, stored: 100, recallable: 80, no_text: 15, pending: 99, platforms: {} } });
  for (const fn of ["confirmWorkProposal", "dismissWorkProposal", "createWork", "addWorkLink", "setWorkObjectives"]) {
    api[fn].mockResolvedValue({});
  }
});

function renderPanel() {
  render(
    <AppProviders>
      <WorkPanel />
    </AppProviders>,
  );
}

describe("Collaborator's Work mode", () => {
  it("asks about what it noticed, and confirms only in the owner's words", async () => {
    renderPanel();
    expect(await screen.findByText(PROPOSAL.question)).toBeInTheDocument();
    const card = screen.getByText(PROPOSAL.question).closest("div").parentElement;
    const confirm = within(card).getByRole("button", { name: /confirm/i });
    expect(confirm).toBeDisabled(); // no summary yet
    await userEvent.click(within(card).getByLabelText("Summary"));
    await userEvent.paste("Working AI search optimization, in public.");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.confirmWorkProposal).toHaveBeenCalledWith(expect.objectContaining({
      key: "container:c-1", summary: "Working AI search optimization, in public.", kind: "series", role: "author",
    })));
  });

  it("dismisses a proposal that is not the owner's", async () => {
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: /not mine/i }));
    await waitFor(() => expect(api.dismissWorkProposal).toHaveBeenCalledWith("container:c-1"));
  });

  it("shows how works relate and what they serve", async () => {
    renderPanel();
    expect(await screen.findByText("aindy-runtime", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText(/executes Nodus/, { selector: "span" })).toBeInTheDocument();
    const serves = screen.getAllByRole("checkbox", { name: "Platform Enablement" });
    expect(serves[0]).toBeChecked(); // aindy-runtime
    expect(serves[1]).not.toBeChecked(); // Nodus
    await userEvent.click(serves[1]);
    await waitFor(() => expect(api.setWorkObjectives).toHaveBeenCalledWith("w-nd", ["o-1"]));
  });

  it("adds a work, with a summary", async () => {
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: /add a work/i }));
    const names = screen.getAllByLabelText("Name");
    await userEvent.click(names[names.length - 1]);
    await userEvent.paste("A.I.N.D.Y.");
    const summaries = screen.getAllByLabelText("Summary");
    await userEvent.click(summaries[summaries.length - 1]);
    await userEvent.paste("Persistent execution partner.");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(api.createWork).toHaveBeenCalledWith(expect.objectContaining({
      name: "A.I.N.D.Y.", summary: "Persistent execution partner.", kind: "project",
    })));
  });

  it("shows how much published writing the agent can recall, and stores a batch on request", async () => {
    renderPanel();
    expect(await screen.findByText("40 of 214 pieces recallable by the agent")).toBeInTheDocument();
    expect(screen.getByText(/DEV 30\/143 · YouTube 0\/15 \(15 with no text\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /store a batch now/i }));
    await waitFor(() => expect(api.storePublishedWriting).toHaveBeenCalled());
  });

  it("shows a work's success in the owner's words, and saves an edit to it", async () => {
    api.updateWork.mockResolvedValue({});
    renderPanel();
    expect(await screen.findByText(/Resolution, not rankings/)).toBeInTheDocument();
    const edits = screen.getAllByRole("button", { name: /^edit$/i });
    await userEvent.click(edits[2]);
    const boxes = screen.getAllByLabelText("How I judge success");
    const box = boxes[boxes.length - 1]; // the work being edited; the proposal card has its own
    await userEvent.clear(box);
    await userEvent.type(box, "The right entity, said correctly.");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(api.updateWork).toHaveBeenCalledWith("w-ai", expect.objectContaining({
      success_criteria: "The right entity, said correctly.",
    })));
  });

  it("shows exactly what the agent is told", async () => {
    renderPanel();
    await screen.findByText("aindy-runtime", { selector: "p" });
    expect(screen.getByText(/What the agent is told/)).toBeInTheDocument();
    expect(screen.getByText(/executes Nodus$/m, { selector: "pre" })).toBeInTheDocument();
  });
});
