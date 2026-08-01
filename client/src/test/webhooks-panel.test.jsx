import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/operator.js", () => ({
  getWebhooks: vi.fn(),
  createWebhook: vi.fn(),
  deleteWebhook: vi.fn(),
}));

// AuthContext gates the panel on isAdmin.
vi.mock("../context/AuthContext", () => ({ useAuth: () => ({ isAdmin: true }) }));

import WebhooksPanel from "../components/platform/WebhooksPanel";
import { getWebhooks, createWebhook, deleteWebhook } from "../api/operator.js";

const HOOK = {
  id: "wh-1",
  event_type: "task.completed",
  callback_url: "https://example.com/hook",
  signed: false,
  created_at: "2026-07-31T00:00:00Z",
  delivery_successes: 0,
  delivery_failures: 0,
};

beforeEach(() => {
  vi.clearAllMocks();
  getWebhooks.mockResolvedValue({ webhooks: [HOOK] });
  createWebhook.mockResolvedValue({ id: "wh-2", event_type: "x", callback_url: "y" });
  deleteWebhook.mockResolvedValue("");
});

describe("WebhooksPanel", () => {
  it("lists existing subscriptions", async () => {
    render(<WebhooksPanel />);
    expect(await screen.findByText("task.completed")).toBeInTheDocument();
    expect(screen.getByText("https://example.com/hook")).toBeInTheDocument();
  });

  it("validates required fields before creating", async () => {
    render(<WebhooksPanel />);
    await screen.findByText("task.completed");
    fireEvent.click(screen.getByRole("button", { name: "Create subscription" }));
    // No event_type/callback_url entered → must not call the API.
    expect(createWebhook).not.toHaveBeenCalled();
  });

  it("creates a subscription from the form", async () => {
    render(<WebhooksPanel />);
    await screen.findByText("task.completed");
    fireEvent.change(screen.getByPlaceholderText(/event_type/i), { target: { value: "order.paid" } });
    fireEvent.change(screen.getByPlaceholderText(/callback_url/i), { target: { value: "https://x.test/h" } });
    fireEvent.click(screen.getByRole("button", { name: "Create subscription" }));
    await waitFor(() => expect(createWebhook).toHaveBeenCalledWith({ event_type: "order.paid", callback_url: "https://x.test/h", secret: undefined }));
  });

  it("requires a confirm before deleting", async () => {
    render(<WebhooksPanel />);
    await screen.findByText("task.completed");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteWebhook).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(deleteWebhook).toHaveBeenCalledWith("wh-1"));
  });

  it("shows an empty state with no subscriptions", async () => {
    getWebhooks.mockResolvedValue({ webhooks: [] });
    render(<WebhooksPanel />);
    expect(await screen.findByText(/no webhook subscriptions/i)).toBeInTheDocument();
  });
});
