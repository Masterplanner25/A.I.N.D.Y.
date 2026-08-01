import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/social.js", () => ({
  getSocialAnalytics: vi.fn(),
}));

import SocialAnalytics from "../components/app/SocialAnalytics";
import { getSocialAnalytics } from "../api/social.js";

// Captured verbatim from a live GET /apps/social/analytics — post-unwrapEnvelope.
// Building the UI against the recorded real shape rather than an invented fixture is
// deliberate: the surface this replaced shipped a form whose fields the API never
// accepted, because nothing ever compared the two.
const LIVE_SHAPE = {
  overview: {
    post_count: 2,
    total_impressions: 3,
    total_clicks: 0,
    avg_engagement_score: 0.0,
    avg_conversion_signal: 0.0,
  },
  top_posts: [
    { id: "8591ff5c", content: "post-restart smoke", engagement_score: 0.0, conversion_signal: 0.0, impressions: 2, clicks: 0 },
    { id: "fc0a7882", content: "post-rebuild smoke", engagement_score: 0.0, conversion_signal: 0.0, impressions: 1, clicks: 0 },
  ],
  trend: [{ date: "2026-07-23", impressions: 3, clicks: 0, avg_engagement_score: 0.0 }],
  signals: [
    { type: "success", reason: "top_performing_content", engagement_score: 0.0, content: "post-restart smoke" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  getSocialAnalytics.mockResolvedValue(LIVE_SHAPE);
});

describe("SocialAnalytics", () => {
  it("renders the overview tiles from the live shape", async () => {
    render(<SocialAnalytics />);
    expect(await screen.findByText("Content Performance")).toBeInTheDocument();
    expect(screen.getByText("Posts")).toBeInTheDocument();
    expect(screen.getByText("Impressions")).toBeInTheDocument();
    expect(screen.getByText("Avg Conversion")).toBeInTheDocument();
  });

  it("renders signals — the field the old Feed panel dropped", async () => {
    render(<SocialAnalytics />);
    expect(await screen.findByText("Signals")).toBeInTheDocument();
    expect(screen.getByText("Best-performing post")).toBeInTheDocument();
  });

  it("maps each signal type to its own treatment", async () => {
    getSocialAnalytics.mockResolvedValue({
      ...LIVE_SHAPE,
      signals: [
        { type: "success", reason: "top_performing_content", engagement_score: 9.1, content: "a" },
        { type: "failure", reason: "low_engagement_content", engagement_score: 1.2, content: "b" },
        { type: "pattern", reason: "repeating_high_engagement_pattern", engagement_score: 8.4, count: 3 },
      ],
    });
    render(<SocialAnalytics />);
    expect(await screen.findByText("Best-performing post")).toBeInTheDocument();
    expect(screen.getByText("Seen but not engaged with")).toBeInTheDocument();
    expect(screen.getByText("Repeating high engagement")).toBeInTheDocument();
    expect(screen.getByText("3 posts")).toBeInTheDocument();
  });

  it("renders trend and top content", async () => {
    render(<SocialAnalytics />);
    expect(await screen.findByText("Performance Trend")).toBeInTheDocument();
    expect(screen.getByText("2026-07-23")).toBeInTheDocument();
    expect(screen.getByText("Top Content")).toBeInTheDocument();
    expect(screen.getByText("post-rebuild smoke")).toBeInTheDocument();
  });

  it("shows an empty state instead of zeroed tiles when there are no posts", async () => {
    getSocialAnalytics.mockResolvedValue({
      overview: { post_count: 0, total_impressions: 0, total_clicks: 0, avg_engagement_score: 0, avg_conversion_signal: 0 },
      top_posts: [],
      trend: [],
      signals: [],
    });
    render(<SocialAnalytics />);
    expect(await screen.findByText(/No content activity yet/)).toBeInTheDocument();
    expect(screen.queryByText("Signals")).not.toBeInTheDocument();
  });

  it("surfaces a load failure with a retry that refetches", async () => {
    getSocialAnalytics.mockRejectedValueOnce(new Error("backend down"));
    render(<SocialAnalytics />);
    expect(await screen.findByText("Failed to load analytics")).toBeInTheDocument();
    expect(screen.getByText("backend down")).toBeInTheDocument();

    getSocialAnalytics.mockResolvedValue(LIVE_SHAPE);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Content Performance")).toBeInTheDocument();
  });

  it("tolerates a response with fields missing entirely", async () => {
    getSocialAnalytics.mockResolvedValue({ overview: { post_count: 1 } });
    render(<SocialAnalytics />);
    expect(await screen.findByText("Content Performance")).toBeInTheDocument();
    // No signals/trend/top_posts keys at all must not throw.
    expect(screen.queryByText("Signals")).not.toBeInTheDocument();
  });

  it("refetches on Refresh", async () => {
    render(<SocialAnalytics />);
    await screen.findByText("Content Performance");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(getSocialAnalytics).toHaveBeenCalledTimes(2));
  });
});
