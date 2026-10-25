/**
 * The release handoff on Collaborator (RELEASE_HANDOFF_SPEC §6). The properties that matter: a run
 * waiting at the gate says so and links straight to GitHub to approve, a stopped one says why, a
 * finished one names the approver and the wait, a tag is handed off from the form, and a refusal is
 * shown in the server's words. Phase 3 (§7.3): with can_decide the card offers Approve and Reject, and
 * neither is sent before a confirm step that says what it does.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AppProviders } from "./utils";

const api = vi.hoisted(() => ({ listReleases: vi.fn(), handOffRelease: vi.fn(), decideRelease: vi.fn() }));
vi.mock("../api/releases.js", () => api);

const RUN_URL = "https://github.com/Masterplanner25/aindy-runtime/actions/runs/38025672838";
const base = { repo: "Masterplanner25/aindy-runtime", run_url: RUN_URL, notified: {} };
const now = new Date().toISOString();
const AT_GATE = { ...base, id: "h1", tag: "v2.28.0", version: "2.28.0", stage: "at_gate", stage_at: now,
  history: [{ stage: "requested", at: now }, { stage: "running", at: now }, { stage: "at_gate", at: now }] };
const DONE = { ...base, id: "h2", tag: "v2.27.0", version: "2.27.0", stage: "done", stage_at: now, finished_at: now,
  approved_by: "Masterplanner25", gate_wait_seconds: 634, history: [] };
const FAILED = { ...base, id: "h3", tag: "v2.26.1", version: "2.26.1", stage: "failed", stage_at: now, finished_at: now,
  failure: { reason: "job_failed", job: "Install Smoke Test", conclusion: "failure", url: "https://github.com/x/job/5" },
  history: [] };
const OLD = { ...DONE, id: "h4", tag: "v2.25.0", version: "2.25.0", finished_at: "2026-01-01T00:00:00Z" };

let ReleasePanel;

beforeAll(async () => {
  ReleasePanel = (await import("../components/app/ReleasePanel.jsx")).default;
});

beforeEach(() => {
  api.listReleases.mockReset();
  api.handOffRelease.mockReset();
  api.decideRelease.mockReset();
});

const renderPanel = () => render(<AppProviders><ReleasePanel /></AppProviders>);

it("asks for approval at the gate and links to GitHub", async () => {
  api.listReleases.mockResolvedValue({ handoffs: [AT_GATE] });
  renderPanel();
  expect(await screen.findByText(/aindy-runtime 2\.28\.0 is waiting for your approval/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Approve on GitHub" })).toHaveAttribute("href", RUN_URL);
});

it("says who approved a finished release, why a stopped one stopped, and drops old ones", async () => {
  api.listReleases.mockResolvedValue({ handoffs: [DONE, FAILED, OLD] });
  renderPanel();
  expect(await screen.findByText(/Approved by Masterplanner25 after 10 min 34 s at the gate/)).toBeInTheDocument();
  expect(screen.getByText("Stopped: Install Smoke Test ended failure")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open on GitHub" })).toHaveAttribute("href", "https://github.com/x/job/5");
  expect(screen.queryByTestId("release-v2.25.0")).not.toBeInTheDocument();
});

it("hands a tag off and shows a refusal in the server's words", async () => {
  api.listReleases.mockResolvedValueOnce({ handoffs: [] }).mockResolvedValue({ handoffs: [{ ...AT_GATE, stage: "requested" }] });
  api.handOffRelease.mockResolvedValueOnce({ id: "h1" }).mockRejectedValueOnce(new Error("v2.28.0 is already handed off"));
  const user = userEvent.setup();
  renderPanel();
  await user.click(await screen.findByRole("button", { name: "Hand off a release" }));
  const input = screen.getByLabelText("Release tag");
  await user.type(input, "v2.28.0");
  await user.click(screen.getByRole("button", { name: "Follow" }));
  await waitFor(() => expect(api.handOffRelease).toHaveBeenCalledWith("v2.28.0"));
  expect(await screen.findByText(/Looking for the publish run/)).toBeInTheDocument();
  await user.type(input, "v2.28.0");
  await user.click(screen.getByRole("button", { name: "Follow" }));
  expect(await screen.findByText("v2.28.0 is already handed off")).toBeInTheDocument();
});

it("shows only the handoff button when the endpoint cannot be reached, and no second text box", async () => {
  api.listReleases.mockRejectedValue(new Error("offline"));
  renderPanel();
  expect(await screen.findByRole("button", { name: "Hand off a release" })).toBeInTheDocument();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByText("Releases")).not.toBeInTheDocument();
});

it("offers no Approve button without can_decide", async () => {
  api.listReleases.mockResolvedValue({ handoffs: [AT_GATE] });
  renderPanel();
  await screen.findByText(/is waiting for your approval/);
  expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
});

it("approves only after the confirm step, then says it is waiting for GitHub", async () => {
  const decided = { ...AT_GATE, can_decide: false, decision: { stage: "decision", state: "approved", via: "collaborator", at: now } };
  api.listReleases.mockResolvedValueOnce({ handoffs: [{ ...AT_GATE, can_decide: true }] }).mockResolvedValue({ handoffs: [decided] });
  api.decideRelease.mockResolvedValue(decided);
  const user = userEvent.setup();
  renderPanel();
  await user.click(await screen.findByRole("button", { name: "Approve" }));
  expect(api.decideRelease).not.toHaveBeenCalled();
  expect(screen.getByText("Publish aindy-runtime 2.28.0 to PyPI, approving as you on GitHub?")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Yes, publish" }));
  await waitFor(() => expect(api.decideRelease).toHaveBeenCalledWith("h1", "approve"));
  expect(await screen.findByText(/Approved from A\.I\.N\.D\.Y\. at .*waiting for GitHub to move/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
});

it("cancels a rejection without sending it, and shows GitHub's refusal in its words", async () => {
  api.listReleases.mockResolvedValue({ handoffs: [{ ...AT_GATE, can_decide: true }] });
  api.decideRelease.mockRejectedValue(new Error("GitHub says the gate was already decided"));
  const user = userEvent.setup();
  renderPanel();
  await user.click(await screen.findByRole("button", { name: "Reject" }));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(api.decideRelease).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Reject" }));
  await user.click(screen.getByRole("button", { name: "Yes, reject" }));
  expect(await screen.findByText("GitHub says the gate was already decided")).toBeInTheDocument();
  expect(api.decideRelease).toHaveBeenCalledWith("h1", "reject");
});
