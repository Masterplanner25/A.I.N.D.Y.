import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import PlatformNav, { PLATFORM_LINKS } from "../components/platform/PlatformNav";

// The platform SPA registers eight routes. Before this nav existed it rendered no links
// at all, so only /platform/flows was reachable (via the product app's "Open platform"
// button) and the other seven panels could only be reached by typing a URL.
describe("PlatformNav", () => {
  it("links to every registered platform route", () => {
    render(
      <MemoryRouter initialEntries={["/flows"]}>
        <PlatformNav />
      </MemoryRouter>
    );

    const expected = [
      "/agent",
      "/approvals",
      "/registry",
      "/flows",
      "/executions",
      "/observability",
      "/health",
      "/trace",
      "/users",
    ];

    const actual = [];
    for (const link of PLATFORM_LINKS) {
      actual.push(link.to);
      const el = screen.getByRole("link", { name: link.label });
      expect(el).toHaveAttribute("href", link.to);
    }
    expect(actual).toEqual(expected);
  });

  it("marks the current route as active", () => {
    render(
      <MemoryRouter initialEntries={["/health"]}>
        <PlatformNav />
      </MemoryRouter>
    );

    expect(screen.getByRole("link", { name: "Health" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Flow Engine" })).not.toHaveAttribute("aria-current");
  });

  it("offers a way back to the product app", () => {
    render(
      <MemoryRouter initialEntries={["/flows"]}>
        <PlatformNav />
      </MemoryRouter>
    );

    expect(screen.getByRole("link", { name: /back to app/i })).toHaveAttribute("href", "/");
  });
});
