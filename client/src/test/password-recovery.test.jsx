import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

// Password recovery is the one flow a locked-out user reaches, so the properties worth
// locking are the security ones: the confirmation must not reveal whether an account
// exists, and reset must not try to start a session it was never handed.

afterEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.doUnmock("../api/auth.js");
  vi.doUnmock("../context/AuthContext");
});

function mockUnauthenticated() {
  vi.doMock("../context/AuthContext", () => ({
    useAuth: () => ({ isAuthenticated: false }),
  }));
}

describe("ForgotPassword", () => {
  it("shows the same neutral confirmation regardless of whether the address exists", async () => {
    mockUnauthenticated();
    const requestPasswordReset = vi.fn().mockResolvedValue(true);
    vi.doMock("../api/auth.js", () => ({ requestPasswordReset }));

    const { default: ForgotPassword } = await import("../pages/ForgotPassword.jsx");
    render(
      <MemoryRouter>
        <ForgotPassword />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText("you@aindy.ai"), {
      target: { value: "someone@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => expect(screen.getByText(/reset link sent/i)).toBeInTheDocument());
    expect(requestPasswordReset).toHaveBeenCalledWith("someone@example.com");
    // Conditional phrasing only — never "no such account" / "we sent you an email".
    expect(screen.getByText(/if/i)).toBeInTheDocument();
    expect(screen.queryByText(/no account|not registered|does not exist/i)).toBeNull();
  });

  it("surfaces 503 plainly — it describes the deployment, not an account", async () => {
    mockUnauthenticated();
    const err = Object.assign(new Error("API Error (503)"), { status: 503 });
    vi.doMock("../api/auth.js", () => ({
      requestPasswordReset: vi.fn().mockRejectedValue(err),
    }));

    const { default: ForgotPassword } = await import("../pages/ForgotPassword.jsx");
    render(
      <MemoryRouter>
        <ForgotPassword />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText("you@aindy.ai"), {
      target: { value: "someone@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() =>
      expect(screen.getByText(/no email channel configured/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/reset link sent/i)).toBeNull();
  });
});

describe("ResetPassword", () => {
  it("submits the token with the new password and sends the user to sign in", async () => {
    mockUnauthenticated();
    const resetPassword = vi.fn().mockResolvedValue(true);
    vi.doMock("../api/auth.js", () => ({ resetPassword }));

    const { default: ResetPassword } = await import("../pages/ResetPassword.jsx");
    render(
      <MemoryRouter initialEntries={["/reset-password?token=tok-123"]}>
        <ResetPassword />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText("At least 8 characters"), {
      target: { value: "brand-new-pass" },
    });
    fireEvent.change(screen.getByPlaceholderText("........"), {
      target: { value: "brand-new-pass" },
    });
    fireEvent.click(screen.getByRole("button", { name: /set new password/i }));

    await waitFor(() =>
      expect(resetPassword).toHaveBeenCalledWith({
        token: "tok-123",
        newPassword: "brand-new-pass",
      }),
    );
    // Reset returns no session token, so nothing may be stored.
    expect(window.localStorage.getItem("token")).toBeNull();
  });

  it("enforces the 8-character floor before calling the API", async () => {
    mockUnauthenticated();
    const resetPassword = vi.fn();
    vi.doMock("../api/auth.js", () => ({ resetPassword }));

    const { default: ResetPassword } = await import("../pages/ResetPassword.jsx");
    render(
      <MemoryRouter initialEntries={["/reset-password?token=tok-123"]}>
        <ResetPassword />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText("At least 8 characters"), {
      target: { value: "short" },
    });
    fireEvent.change(screen.getByPlaceholderText("........"), {
      target: { value: "short" },
    });
    fireEvent.click(screen.getByRole("button", { name: /set new password/i }));

    await waitFor(() =>
      expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument(),
    );
    expect(resetPassword).not.toHaveBeenCalled();
  });

  it("rejects mismatched confirmations without calling the API", async () => {
    mockUnauthenticated();
    const resetPassword = vi.fn();
    vi.doMock("../api/auth.js", () => ({ resetPassword }));

    const { default: ResetPassword } = await import("../pages/ResetPassword.jsx");
    render(
      <MemoryRouter initialEntries={["/reset-password?token=tok-123"]}>
        <ResetPassword />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText("At least 8 characters"), {
      target: { value: "brand-new-pass" },
    });
    fireEvent.change(screen.getByPlaceholderText("........"), {
      target: { value: "different-pass" },
    });
    fireEvent.click(screen.getByRole("button", { name: /set new password/i }));

    await waitFor(() => expect(screen.getByText(/do not match/i)).toBeInTheDocument());
    expect(resetPassword).not.toHaveBeenCalled();
  });
});
