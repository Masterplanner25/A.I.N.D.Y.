/**
 * GENESIS-CLIENT-FABRICATES-FAILURE-1 — the UI must never invent an assistant turn.
 *
 * The defect: `handleSubmit`'s catch appended
 * `{role: "ai", content: "Protocol error. Sync failed. Please try again."}` on ANY error.
 * ui-kit aborts at a hardcoded 30s with `ApiError(408, ...)`, and on 2026-08-23 the server
 * had already persisted the real reply at +15s — so the user was told it failed while the
 * answer sat in the database, and the rendered transcript diverged from the stored one.
 *
 * `test_no_assistant_bubble_is_invented` is the load-bearing one: it fails against the old
 * catch block, which is what makes this a regression test rather than a description.
 */
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import { AppProviders } from "./utils";

const {
  mockStartGenesisSession,
  mockSendGenesisMessage,
  mockGetGenesisSession,
  mockSynthesizeGenesisDraft,
  mockLockMasterPlan,
  mockImportExistingPlan,
  mockGetGenesisDraft,
  mockAuditGenesisDraft,
} = vi.hoisted(() => ({
  mockStartGenesisSession: vi.fn(),
  mockSendGenesisMessage: vi.fn(),
  mockGetGenesisSession: vi.fn(),
  mockSynthesizeGenesisDraft: vi.fn(),
  mockLockMasterPlan: vi.fn(),
  mockImportExistingPlan: vi.fn(),
  mockGetGenesisDraft: vi.fn(),
  mockAuditGenesisDraft: vi.fn(),
}));

vi.mock("../api/masterplan.js", () => ({
  startGenesisSession: mockStartGenesisSession,
  sendGenesisMessage: mockSendGenesisMessage,
  getGenesisSession: mockGetGenesisSession,
  synthesizeGenesisDraft: mockSynthesizeGenesisDraft,
  lockMasterPlan: mockLockMasterPlan,
  importExistingPlan: mockImportExistingPlan,
  getGenesisDraft: mockGetGenesisDraft,
  auditGenesisDraft: mockAuditGenesisDraft,
}));

import Genesis from "../components/app/Genesis";

/** ui-kit's shape: `ApiError(408, "Request timed out after 30 seconds.")`. */
function timeoutError() {
  const err = new Error("Request timed out after 30 seconds.");
  err.status = 408;
  return err;
}

async function startSessionAndSend(text = "my goal is to ship") {
  mockStartGenesisSession.mockResolvedValue({ session_id: 1, reply: "Tell me more." });
  render(
    <AppProviders>
      <Genesis />
    </AppProviders>
  );
  // The button is disabled while the resume effect runs, so wait for it to settle rather
  // than clicking a no-op.
  const startBtn = await screen.findByRole("button", { name: /initialize/i });
  await waitFor(() => expect(startBtn).not.toBeDisabled());
  fireEvent.click(startBtn);
  const box = await screen.findByPlaceholderText(/transmitting signal/i);
  fireEvent.change(box, { target: { value: text } });
  fireEvent.submit(box.closest("form"));
}

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom has no scrollIntoView, and Genesis scrolls on every message change. No existing
  // test drove a send, so this gap had not surfaced before. Without it the effect throws
  // and the failure UI never renders.
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = vi.fn();
  }
  try {
    window.localStorage.clear();
  } catch {
    /* storage blocked — resume simply won't apply */
  }
});

describe("Genesis turn failure", () => {
  it("★ never invents an assistant bubble when the send fails", async () => {
    mockSendGenesisMessage.mockRejectedValue(new Error("Network error."));
    mockGetGenesisSession.mockRejectedValue(new Error("unavailable"));

    await startSessionAndSend();

    // Prove the send actually happened — without this the assertions below would pass
    // trivially on a test that never got as far as the error path.
    await waitFor(() => expect(mockSendGenesisMessage).toHaveBeenCalledTimes(1));

    expect(screen.queryByText(/protocol error/i)).not.toBeInTheDocument();
    // The exact fabricated string, and the shape of it generally.
    expect(screen.queryByText(/sync failed/i)).not.toBeInTheDocument();
  });

  it("attaches the failure to the user's own turn, with a retry", async () => {
    mockSendGenesisMessage.mockRejectedValue(new Error("Network error."));
    mockGetGenesisSession.mockRejectedValue(new Error("unavailable"));

    await startSessionAndSend();

    // Scoped to the turn, not just "somewhere on the page": the toast shows the same
    // string, and a toast is exactly what this defect was NOT supposed to be replaced by.
    const retry = await screen.findByRole("button", { name: /retry/i });
    const status = retry.parentElement;
    expect(status).toHaveTextContent(/network error/i);

    // The status sits alongside the user's own turn, not in a chat bubble of its own.
    const turn = screen.getByText("my goal is to ship").closest("div").parentElement;
    expect(turn).toContainElement(retry);

    // The user's text survives exactly once — a failure must not lose or duplicate it.
    expect(screen.getAllByText("my goal is to ship")).toHaveLength(1);
  });

  it("on a 408, recovers the reply from the session instead of reporting failure", async () => {
    // The defining case: the client gave up, the server did not.
    mockSendGenesisMessage.mockRejectedValue(timeoutError());
    mockGetGenesisSession.mockResolvedValue({
      session_id: 1,
      status: "active",
      synthesis_ready: false,
      transcript: [
        { role: "user", content: "my goal is to ship" },
        { role: "assistant", content: "Understood — what is the deadline?" },
      ],
    });

    await startSessionAndSend();

    expect(
      await screen.findByText(/understood — what is the deadline\?/i)
    ).toBeInTheDocument();
    // Recovered, so it is NOT presented as a failure.
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("on a 408 with nothing persisted, marks the turn rather than claiming it failed outright", async () => {
    mockSendGenesisMessage.mockRejectedValue(timeoutError());
    mockGetGenesisSession.mockResolvedValue({
      session_id: 1,
      status: "active",
      transcript: [{ role: "user", content: "my goal is to ship" }],
    });

    await startSessionAndSend();

    // Wording matters: a timeout may still land, so it must not read as a hard failure.
    expect(await screen.findByText(/still sending/i)).toBeInTheDocument();
  });

  it("retry updates the existing turn instead of duplicating the message", async () => {
    mockSendGenesisMessage.mockRejectedValueOnce(new Error("Network error."));
    mockGetGenesisSession.mockRejectedValue(new Error("unavailable"));

    await startSessionAndSend();

    const retry = await screen.findByRole("button", { name: /retry/i });
    mockSendGenesisMessage.mockResolvedValueOnce({
      reply: "Understood.",
      synthesis_ready: false,
    });
    fireEvent.click(retry);

    expect(await screen.findByText("Understood.")).toBeInTheDocument();
    // The whole point of keying retry to the turn id.
    expect(screen.getAllByText("my goal is to ship")).toHaveLength(1);
  });
});
