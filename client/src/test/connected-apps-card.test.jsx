import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Connected apps (owner, 2026-11-11): the AIs reading A.I.N.D.Y. over MCP, seen and ended from Settings.

afterEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.doUnmock("../api/mcpGrants.js");
});

async function renderCard(api) {
  vi.doMock("../api/mcpGrants.js", () => api);
  const { default: ConnectedAppsCard } = await import("../components/app/ConnectedAppsCard.jsx");
  render(<ConnectedAppsCard />);
}

const CLAUDE = {
  id: "g1", client_id: "c1", client_name: "Claude", redirect_host: "claude.ai",
  scopes: ["memory.read", "work.context", "work.facts"],
  created_at: "2026-11-11T04:20:25Z", last_used_at: "2026-11-11T04:20:26Z",
};

describe("ConnectedAppsCard", () => {
  it("lists each app by the site it returns to, with what it may read", async () => {
    await renderCard({ listMcpGrants: vi.fn().mockResolvedValue([CLAUDE]), revokeMcpGrant: vi.fn() });

    const row = await screen.findByRole("listitem");
    expect(row).toHaveTextContent("claude.ai");
    expect(row).toHaveTextContent("calls itself Claude");
    expect(row).toHaveTextContent("reads memory, your Works, facts about a Work");
    expect(row).toHaveTextContent("connected");
    expect(row).toHaveTextContent("last used");
  });

  it("disconnects an app", async () => {
    const listMcpGrants = vi.fn().mockResolvedValueOnce([CLAUDE]).mockResolvedValueOnce([]);
    const revokeMcpGrant = vi.fn().mockResolvedValue(undefined);
    await renderCard({ listMcpGrants, revokeMcpGrant });

    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(revokeMcpGrant).toHaveBeenCalledWith("g1"));
    expect(await screen.findByText("No apps connected.")).toBeInTheDocument();
  });

  it("shows the server's sentence on a failure", async () => {
    const err = Object.assign(new Error("API Error (403)"), {
      status: 403, data: JSON.stringify({ detail: "Connected apps need a signed-in session." }),
    });
    await renderCard({ listMcpGrants: vi.fn().mockRejectedValue(err), revokeMcpGrant: vi.fn() });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Connected apps need a signed-in session."));
    expect(screen.getByText("No apps connected.")).toBeInTheDocument();
  });
});
