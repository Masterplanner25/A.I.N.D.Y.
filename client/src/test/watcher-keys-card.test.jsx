import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// The watcher key (audit D1): made here, shown once, revocable. Without it the watcher's signals never count.

afterEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.doUnmock("../api/watcher.js");
});

async function renderCard(api) {
  vi.doMock("../api/watcher.js", () => api);
  const { default: WatcherKeysCard } = await import("../components/app/WatcherKeysCard.jsx");
  render(<WatcherKeysCard />);
}

describe("WatcherKeysCard", () => {
  it("makes a key and shows it once, with how to run the watcher", async () => {
    const listWatcherKeys = vi.fn().mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ id: "k1", name: "laptop", key_prefix: "aindy_wk", created_at: "2026-11-08T23:00:00Z" }]);
    const createWatcherKey = vi.fn().mockResolvedValue({ key: "aindy_wk_secret_123", id: "k1", name: "laptop" });
    await renderCard({ listWatcherKeys, createWatcherKey, revokeWatcherKey: vi.fn() });

    expect(await screen.findByText("No watcher key yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Make a key" }));

    const fresh = await screen.findByTestId("watcher-key-fresh");
    expect(createWatcherKey).toHaveBeenCalledWith("laptop");
    expect(fresh).toHaveTextContent("aindy_wk_secret_123");
    expect(fresh).toHaveTextContent("won't be shown again");
    expect(fresh).toHaveTextContent("aindy-watcher");
    expect(fresh).not.toHaveTextContent("watcher.py");
    fireEvent.click(screen.getByRole("button", { name: "I've saved it" }));
    expect(screen.queryByTestId("watcher-key-fresh")).toBeNull();
    expect(document.body.textContent).not.toContain("aindy_wk_secret_123");
    expect(screen.getByRole("listitem")).toHaveTextContent("laptop aindy_wk…");
  });

  it("revokes a key", async () => {
    const listWatcherKeys = vi.fn().mockResolvedValueOnce([{ id: "k9", name: "old laptop", key_prefix: "aindy_wk" }])
      .mockResolvedValueOnce([]);
    const revokeWatcherKey = vi.fn().mockResolvedValue(undefined);
    await renderCard({ listWatcherKeys, createWatcherKey: vi.fn(), revokeWatcherKey });

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(revokeWatcherKey).toHaveBeenCalledWith("k9"));
    expect(await screen.findByText("No watcher key yet.")).toBeInTheDocument();
  });

  it("shows the server's sentence on a failure", async () => {
    const err = Object.assign(new Error("API Error (409)"), {
      status: 409, data: JSON.stringify({ detail: "You already have a key named 'laptop'." }),
    });
    await renderCard({ listWatcherKeys: vi.fn().mockResolvedValue([]), createWatcherKey: vi.fn().mockRejectedValue(err),
                       revokeWatcherKey: vi.fn() });
    fireEvent.click(await screen.findByRole("button", { name: "Make a key" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("You already have a key named 'laptop'."));
  });
});
