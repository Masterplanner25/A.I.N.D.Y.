import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AppProviders } from "./utils";

// LeadOutreach is the client face of the Search Execution Layer. The server owns every rule
// (the send gate, the hand-entered contact, "sent cannot be reverted"); these tests pin that
// the UI reflects them instead of inventing its own.

const { mockListLeads, mockListLeadActions, mockSetLeadContact, mockExecute, mockRevert, mockPreview } =
  vi.hoisted(() => ({
    mockListLeads: vi.fn(),
    mockListLeadActions: vi.fn(),
    mockSetLeadContact: vi.fn(),
    mockExecute: vi.fn(),
    mockRevert: vi.fn(),
    mockPreview: vi.fn(),
  }));

vi.mock("../api/search.js", () => ({
  listLeads: mockListLeads,
  listLeadActions: mockListLeadActions,
  setLeadContact: mockSetLeadContact,
  executeLeadActions: mockExecute,
  revertLeadAction: mockRevert,
  previewLeadActions: mockPreview,
}));

import LeadOutreach from "../components/app/LeadOutreach";

const LEADS = [
  { id: 1, company: "Acme Robotics", url: "https://acme.example", search_score: 86, contact_email: null },
  { id: 2, company: "Globex", url: "https://globex.example", search_score: 71, contact_email: "cto@globex.example" },
];
const ACTIONS = [
  { id: 10, company: "Globex", channel: "email", status: "sent", recipient: "cto@globex.example", sent_at: "2026-09-16T17:09:14Z", note: "sent via smtp", draft_subject: "Hello Globex" },
  { id: 11, company: "Acme Robotics", channel: "email", status: "queued", note: "no recipient on lead — add a contact_email to send", draft_subject: "Hello Acme" },
];

function renderIt() {
  return render(
    <AppProviders>
      <LeadOutreach showToast={vi.fn()} />
    </AppProviders>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListLeads.mockResolvedValue(LEADS);
  mockListLeadActions.mockResolvedValue({ actions: ACTIONS, count: ACTIONS.length });
});

describe("LeadOutreach", () => {
  it("renders saved leads with their hand-entered contact", async () => {
    renderIt();
    await screen.findByLabelText("Contact for Acme Robotics");
    expect(screen.getAllByText("Acme Robotics").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Contact for Globex")).toHaveValue("cto@globex.example");
    expect(screen.getByLabelText("Contact for Acme Robotics")).toHaveValue("");
  });

  it("saves a typed contact through the API and reflects the server's answer", async () => {
    mockSetLeadContact.mockResolvedValue({ id: 1, company: "Acme Robotics", contact_email: "buyer@acme.example" });
    renderIt();
    const input = await screen.findByLabelText("Contact for Acme Robotics");
    fireEvent.change(input, { target: { value: "buyer@acme.example" } });
    const row = input.closest("tr");
    fireEvent.click(within(row).getByText("Save"));
    await waitFor(() => expect(mockSetLeadContact).toHaveBeenCalledWith(1, "buyer@acme.example"));
    await waitFor(() => expect(screen.getByLabelText("Contact for Acme Robotics")).toHaveValue("buyer@acme.example"));
  });

  it("offers Revert for a queued action but never for a sent one", async () => {
    renderIt();
    await screen.findByText("sent via smtp");
    const sentRow = screen.getByText("sent via smtp").closest("tr");
    const queuedRow = screen.getByText(/no recipient on lead/).closest("tr");
    expect(within(sentRow).queryByText("Revert")).toBeNull();
    expect(within(queuedRow).getByText("Revert")).toBeInTheDocument();
    expect(within(sentRow).getByText(/to cto@globex.example/)).toBeInTheDocument();
  });

  it("asks before sending email and passes the channel through", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    mockExecute.mockResolvedValue({ status: "executed", actions: [{ status: "sent" }, { status: "queued" }] });
    renderIt();
    await screen.findByLabelText("Contact for Acme Robotics");
    fireEvent.click(screen.getByText("Send email"));
    await waitFor(() => expect(mockExecute).toHaveBeenCalledWith("email"));
    expect(confirmSpy).toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("does not send when the confirmation is declined", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderIt();
    await screen.findByLabelText("Contact for Acme Robotics");
    fireEvent.click(screen.getByText("Send email"));
    expect(mockExecute).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("drafting never asks and never sends", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    mockExecute.mockResolvedValue({ status: "executed", actions: [{ status: "drafted" }] });
    renderIt();
    await screen.findByLabelText("Contact for Acme Robotics");
    fireEvent.click(screen.getByText("Draft outreach"));
    await waitFor(() => expect(mockExecute).toHaveBeenCalledWith("draft"));
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
