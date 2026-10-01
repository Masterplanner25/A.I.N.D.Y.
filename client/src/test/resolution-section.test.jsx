/**
 * The resolution check (RESOLUTION_CHECK_SPEC). The properties: the owner's self-descriptions show side
 * by side; a check starts on request and its progress shows while it runs; each answer shows the owner's
 * three criteria (right entity, correct claims, connections) and opens to the answer itself.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AppProviders } from "./utils";

const api = vi.hoisted(() => ({ getResolution: vi.fn(), startResolution: vi.fn() }));
vi.mock("../api/works.js", () => api);

const DONE = {
  latest: {
    id: "r-1", scope: "core", status: "done", expected: 2, answered: 2, finished_at: "2026-09-30T21:00:00Z",
    questions: [{ key: "direct:n", kind: "direct", text: "What is Nodus?" }],
    answers: [
      { question_key: "direct:n", engine: "perplexity", answer: "Nodus is an orchestration DSL… and a camera mount.",
        claims: [{ text: "a camera mount", status: "incorrect" }],
        scores: { resolution: "mixed", claims_correct: 3, claims_incorrect: 1, claims_unverifiable: 0, facts_covered: 2,
          facts_total: 3, links_stated: 1, links_total: 2, own_sources_cited: ["libraries.io"], other_entities: ["nodus.com"] } },
      { question_key: "direct:n", engine: "claude", error: "anthropic answered HTTP 529" },
    ],
  },
  self_descriptions: [
    { work: "Shawn Knight", platform: "LinkedIn", self_description: "AI Search Optimization Specialist | Founder" },
    { work: "Shawn Knight", platform: "Facebook", self_description: "Helping you get found in AI Search" },
  ],
};

let ResolutionSection;

beforeAll(async () => {
  ResolutionSection = (await import("../components/app/ResolutionSection.jsx")).default;
});

beforeEach(() => {
  vi.clearAllMocks();
  api.getResolution.mockResolvedValue(DONE);
  api.startResolution.mockResolvedValue({});
});

function renderSection() {
  render(
    <AppProviders>
      <ResolutionSection />
    </AppProviders>,
  );
}

describe("The resolution check", () => {
  it("shows the owner's own self-descriptions side by side", async () => {
    renderSection();
    expect(await screen.findByText(/“AI Search Optimization Specialist \| Founder”/)).toBeInTheDocument();
    expect(screen.getByText(/“Helping you get found in AI Search”/)).toBeInTheDocument();
  });

  it("shows the three criteria per engine, and opens to the answer", async () => {
    renderSection();
    expect(await screen.findByText("mixed")).toBeInTheDocument();
    expect(screen.getByText(/3 correct · 1 wrong · 0 unverified/)).toBeInTheDocument();
    expect(screen.getByText(/connections 1\/2/)).toBeInTheDocument();
    expect(screen.getByText(/also: nodus.com/)).toBeInTheDocument();
    expect(screen.getByText(/failed: anthropic answered HTTP 529/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("mixed"));
    expect(await screen.findByText(/incorrect: a camera mount/)).toBeInTheDocument();
  });

  it("starts a check on request", async () => {
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: /run a check/i }));
    await waitFor(() => expect(api.startResolution).toHaveBeenCalledWith("core"));
  });

  it("shows progress while a check runs, and cannot start a second", async () => {
    api.getResolution.mockResolvedValue({ ...DONE, latest: { ...DONE.latest, status: "running", answered: 1 } });
    renderSection();
    expect(await screen.findByText(/Checking… 1 of 2 answers/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run a check/i })).toBeDisabled();
  });
});
