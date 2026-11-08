import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Your own provider keys (FR-59). The runtime's API is write-only: a stored key is never shown,
// only its last four characters. The card must keep it that way on its side too.

afterEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.doUnmock("../api/auth.js");
});

async function renderCard(api) {
  vi.doMock("../api/auth.js", () => api);
  const { default: ProviderKeysCard } = await import("../components/app/ProviderKeysCard.jsx");
  render(<ProviderKeysCard />);
}

describe("ProviderKeysCard", () => {
  it("shows which keys are set by their last four characters, and the rest as not set", async () => {
    await renderCard({
      listProviderKeys: vi.fn().mockResolvedValue([
        { provider: "openai", key_hint: "a1b2", updated_at: "2026-11-08T18:00:00Z" },
      ]),
      setProviderKey: vi.fn(),
      deleteProviderKey: vi.fn(),
    });
    await waitFor(() => expect(screen.getByText(/ending a1b2/)).toBeInTheDocument());
    expect(screen.getAllByText("Not set")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Replace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
  });

  it("saves a key, clears the field, and never puts the key on the page", async () => {
    const listProviderKeys = vi.fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ provider: "perplexity", key_hint: "zz99", updated_at: null }]);
    const setProviderKey = vi.fn().mockResolvedValue({ provider: "perplexity", key_hint: "zz99" });
    await renderCard({ listProviderKeys, setProviderKey, deleteProviderKey: vi.fn() });

    const input = await screen.findByLabelText("Perplexity API key");
    expect(input).toHaveAttribute("type", "password");
    fireEvent.change(input, { target: { value: "  pplx-secret-zz99  " } });
    fireEvent.submit(input.closest("form"));

    await waitFor(() => expect(screen.getByText("Perplexity key saved.")).toBeInTheDocument());
    expect(setProviderKey).toHaveBeenCalledWith("perplexity", "pplx-secret-zz99");
    expect(screen.getByLabelText("Perplexity API key")).toHaveValue("");
    expect(screen.getByText(/ending zz99/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("pplx-secret");
  });

  it("removes a key", async () => {
    const listProviderKeys = vi.fn()
      .mockResolvedValueOnce([{ provider: "deepseek", key_hint: "dd11", updated_at: null }])
      .mockResolvedValueOnce([]);
    const deleteProviderKey = vi.fn().mockResolvedValue(undefined);
    await renderCard({ listProviderKeys, setProviderKey: vi.fn(), deleteProviderKey });

    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.getByText("DeepSeek key removed.")).toBeInTheDocument());
    expect(deleteProviderKey).toHaveBeenCalledWith("deepseek");
    expect(screen.getAllByText("Not set")).toHaveLength(4);
  });

  it("says plainly when the server has not switched keys on (503)", async () => {
    const err = Object.assign(new Error("API Error (503)"), { status: 503, data: "{}" });
    await renderCard({
      listProviderKeys: vi.fn().mockResolvedValue([]),
      setProviderKey: vi.fn().mockRejectedValue(err),
      deleteProviderKey: vi.fn(),
    });
    const input = await screen.findByLabelText("OpenAI API key");
    fireEvent.change(input, { target: { value: "sk-test" } });
    fireEvent.submit(input.closest("form"));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Provider keys aren't switched on for this server yet."),
    );
  });

  it("shows the runtime's own sentence for a rejected key", async () => {
    const body = JSON.stringify({ detail: { error: "invalid_provider_key", message: "That key is too short." } });
    const err = Object.assign(new Error("API Error (422)"), { status: 422, data: body });
    await renderCard({
      listProviderKeys: vi.fn().mockResolvedValue([]),
      setProviderKey: vi.fn().mockRejectedValue(err),
      deleteProviderKey: vi.fn(),
    });
    const input = await screen.findByLabelText("Anthropic API key");
    fireEvent.change(input, { target: { value: "x" } });
    fireEvent.submit(input.closest("form"));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("That key is too short."));
  });
});
