import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { mockRecordSearchFeedback } = vi.hoisted(() => ({
  mockRecordSearchFeedback: vi.fn(),
}));

vi.mock("../api/search.js", () => ({
  recordSearchFeedback: mockRecordSearchFeedback,
}));

import SearchResults from "../components/app/SearchResults";

const SAMPLE = [
  { title: "Cloud Security Inc", url: "https://sec.io", snippet: "s", score: 0.76, metadata: {} },
  { title: "Generic Co", url: null, snippet: "g", score: 0.36, metadata: {} },
];

/**
 * `AINDY_SEARCH_OUTCOME_WEIGHTING` ranks by whether a result actually worked. Four of the
 * six signals the backend understands are IMPLICIT — click 0.3, dwell 0.5, convert 1.0,
 * dismiss -0.3 — so the feedback capture was designed as instrumentation, not as a rating
 * widget. The route, the aggregation and the ranking nudge have existed since Search v4 §8
 * with nothing calling them: `search_result_feedback` had 0 rows on 2026-09-06, after the
 * first real research query.
 *
 * These tests exist mostly to pin the NEGATIVE properties. Telemetry that breaks the thing
 * it measures is worse than no telemetry, so the important assertions are that a click
 * still navigates and that a failing request is invisible.
 */
describe("SearchResults click feedback", () => {
  beforeEach(() => {
    mockRecordSearchFeedback.mockReset();
    mockRecordSearchFeedback.mockResolvedValue({});
  });

  it("records a click signal against the query and the result url", async () => {
    render(<SearchResults results={SAMPLE} query="AI Agent Harness" />);

    fireEvent.click(screen.getByText("Cloud Security Inc"));

    await waitFor(() =>
      expect(mockRecordSearchFeedback).toHaveBeenCalledWith(
        "AI Agent Harness",
        "https://sec.io",
        "click",
      ),
    );
  });

  it("records nothing without a query — the weights are aggregated per query", async () => {
    render(<SearchResults results={SAMPLE} />);

    fireEvent.click(screen.getByText("Cloud Security Inc"));

    // An unattributable row is worse than no row: it inflates the ledger without informing
    // the ranking, which is the failure the soak audit is about.
    await waitFor(() => expect(mockRecordSearchFeedback).not.toHaveBeenCalled());
  });

  it("leaves the anchor intact so the result still opens", () => {
    render(<SearchResults results={SAMPLE} query="q" />);

    const link = screen.getByText("Cloud Security Inc");
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "https://sec.io");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("survives a rejected feedback request without an unhandled rejection", async () => {
    mockRecordSearchFeedback.mockRejectedValue(new Error("500"));
    const onUnhandled = vi.fn();
    window.addEventListener("unhandledrejection", onUnhandled);

    render(<SearchResults results={SAMPLE} query="q" />);
    fireEvent.click(screen.getByText("Cloud Security Inc"));

    await waitFor(() => expect(mockRecordSearchFeedback).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(onUnhandled).not.toHaveBeenCalled();
    window.removeEventListener("unhandledrejection", onUnhandled);
  });

  it("survives a synchronous throw — a link must never be broken by telemetry", () => {
    mockRecordSearchFeedback.mockImplementation(() => {
      throw new Error("route misconfigured");
    });

    render(<SearchResults results={SAMPLE} query="q" />);

    // Would propagate out of the onClick handler and break the navigation if unguarded.
    expect(() => fireEvent.click(screen.getByText("Cloud Security Inc"))).not.toThrow();
  });

  it("does not fire for a result with no url — there is nothing to reference", async () => {
    render(<SearchResults results={SAMPLE} query="q" />);

    fireEvent.click(screen.getByText("Generic Co"));

    await waitFor(() => expect(mockRecordSearchFeedback).not.toHaveBeenCalled());
  });
});
