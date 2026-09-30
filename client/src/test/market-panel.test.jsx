/**
 * Collaborator's Market mode (MARKET_MODEL_SPEC §4, §6). The properties that matter: a proposal is
 * confirmed only once the owner says what it is (and a segment only with a buyer), a saved lead
 * dismissed stays a lead, every segment shows its status and moving it is one choice, and the
 * owner can read exactly what the agent is told.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AppProviders } from "./utils";

const api = vi.hoisted(() => ({
  getMarket: vi.fn(),
  listMarketProposals: vi.fn(),
  confirmMarketProposal: vi.fn(),
  dismissMarketProposal: vi.fn(),
  createSegment: vi.fn(),
  updateSegment: vi.fn(),
  deleteSegment: vi.fn(),
  setSegmentWorks: vi.fn(),
  createMarketEntity: vi.fn(),
  deleteMarketEntity: vi.fn(),
  findSegmentBuyers: vi.fn(),
}));

vi.mock("../api/market.js", () => api);

const KINDS = {
  alternative: "what the buyer would choose instead",
  channel: "where the buyer gathers",
  intermediary: "who sells, integrates or recommends",
  voice: "who shapes how the buyer thinks",
  exemplar: "a named organisation that fits",
};
const SEGMENT = {
  id: "s-1", name: "Platform teams shipping agents", buyer: "head of platform", problem: "pilots fall over",
  category_terms: ["AgentOps"], status: "hypothesis", provenance: "confirmed",
  works: [{ id: "w-rt", name: "aindy-runtime" }], evidence: [],
};
const LEAD = {
  key: "lead:6", source: "lead", kind: null, name: "Crn", url: "https://www.crn.com/news/ai/ahead",
  question: "Lead search saved 'Crn' as a lead. Is it market research: an alternative, a channel, an intermediary, a voice or an exemplar?",
  note: "Saved as a lead by the search 'companies building AI agents'",
  evidence: [{ claim: "AHEAD has embedded AI into its own operations.", source_url: "https://www.crn.com/news/ai/ahead" }],
  category_terms: [], works: [],
};
const AGENT_SEGMENT = {
  key: "agent:a-1", source: "agent", kind: "segment", name: "Brands losing AI-answer visibility",
  question: "Is 'Brands losing AI-answer visibility' a segment of your market?", buyer: "", problem: "",
  category_terms: ["AEO"], works: [], evidence: [],
};

let MarketPanel;

beforeAll(async () => {
  MarketPanel = (await import("../components/app/MarketPanel.jsx")).default;
});

beforeEach(() => {
  vi.clearAllMocks();
  api.getMarket.mockResolvedValue({
    segments: [SEGMENT],
    entities: [{ id: "e-1", segment_id: "s-1", kind: "alternative", name: "Onereach", url: null, note: null, evidence: [] }],
    works_available: [{ id: "w-rt", name: "aindy-runtime" }, { id: "w-nd", name: "Nodus" }],
    vocabulary: { statuses: ["hypothesis", "testing", "validated", "abandoned"], kinds: KINDS },
    agent_block: "## The user's market\n- Platform teams shipping agents — HYPOTHESIS. Buyer: head of platform.",
  });
  api.listMarketProposals.mockResolvedValue({ proposals: [LEAD, AGENT_SEGMENT] });
  for (const fn of ["confirmMarketProposal", "dismissMarketProposal", "updateSegment", "setSegmentWorks"]) {
    api[fn].mockResolvedValue({});
  }
});

function renderPanel() {
  render(
    <AppProviders>
      <MarketPanel />
    </AppProviders>,
  );
}

const cardOf = (question) => screen.getByText(question).closest("div").parentElement;

describe("Collaborator's Market mode", () => {
  it("re-files a saved lead only once the owner says what it is, in their words", async () => {
    renderPanel();
    await screen.findByText(LEAD.question);
    const card = cardOf(LEAD.question);
    const confirm = within(card).getByRole("button", { name: /confirm/i });
    expect(confirm).toBeDisabled();
    await userEvent.selectOptions(within(card).getByLabelText("What Crn is"), "intermediary");
    const name = within(card).getByLabelText("Name for Crn");
    await userEvent.clear(name);
    await userEvent.type(name, "AHEAD");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.confirmMarketProposal).toHaveBeenCalledWith(
      { key: "lead:6", kind: "intermediary", name: "AHEAD" },
    ));
  });

  it("keeps a dismissed saved lead as a lead", async () => {
    renderPanel();
    await screen.findByText(LEAD.question);
    await userEvent.click(within(cardOf(LEAD.question)).getByRole("button", { name: /it's a lead/i }));
    await waitFor(() => expect(api.dismissMarketProposal).toHaveBeenCalledWith("lead:6"));
  });

  it("confirms a proposed segment only with a buyer", async () => {
    renderPanel();
    await screen.findByText(AGENT_SEGMENT.question);
    const card = cardOf(AGENT_SEGMENT.question);
    const confirm = within(card).getByRole("button", { name: /confirm/i });
    expect(confirm).toBeDisabled();
    await userEvent.click(within(card).getByLabelText("Buyer"));
    await userEvent.paste("marketing lead at a mid-size brand");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.confirmMarketProposal).toHaveBeenCalledWith(expect.objectContaining({
      key: "agent:a-1", kind: "segment", buyer: "marketing lead at a mid-size brand", category_terms: ["AEO"],
    })));
  });

  it("shows each segment's status, and moving it is one choice", async () => {
    renderPanel();
    const status = await screen.findByLabelText(`Status of ${SEGMENT.name}`);
    expect(status).toHaveValue("hypothesis");
    await userEvent.selectOptions(status, "testing");
    await waitFor(() => expect(api.updateSegment).toHaveBeenCalledWith("s-1", { status: "testing" }));
    expect(screen.getByText("Onereach")).toBeInTheDocument();
  });

  it("ties a segment to the works that serve it", async () => {
    renderPanel();
    const nodus = await screen.findByRole("checkbox", { name: "Nodus" });
    await userEvent.click(nodus);
    await waitFor(() => expect(api.setSegmentWorks).toHaveBeenCalledWith("s-1", ["w-rt", "w-nd"]));
  });

  it("finds buyers inside a segment and says where everything went", async () => {
    api.findSegmentBuyers.mockResolvedValue({
      segment: SEGMENT.name, count: 1, dropped: 2, retired: 1, proposed: [{ kind: "alternative", name: "Gumloop" }],
      leads: [{ id: 9, company: "OpenTeams", url: "https://job-boards.greenhouse.io/openteams/jobs/1",
        overall_score: 82, reasoning: "Hiring to build an internal agent platform." }],
    });
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: /find buyers/i }));
    await waitFor(() => expect(api.findSegmentBuyers).toHaveBeenCalledWith("s-1"));
    expect(await screen.findByText(/1 buyer saved to Leads · 1 proposed above as market entries · 1 earlier lead moved out of Leads · 2 not this segment/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "OpenTeams" })).toHaveAttribute("href", "https://job-boards.greenhouse.io/openteams/jobs/1");
  });

  it("shows exactly what the agent is told", async () => {
    renderPanel();
    await screen.findByLabelText(`Status of ${SEGMENT.name}`);
    expect(screen.getByText(/HYPOTHESIS\. Buyer: head of platform\.$/m, { selector: "pre" })).toBeInTheDocument();
  });
});
