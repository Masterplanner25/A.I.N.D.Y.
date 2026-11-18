/**
 * DIRECTING_TIME_SPEC §5: under Focus quality, one line of directing time, shown only when there are prompts,
 * and always saying it is not in the score.
 */
import { render, screen, waitFor } from "@testing-library/react";

import KPIDashboard from "../components/shared/KPIDashboard";
import { directingNote, fmtMinutes } from "../utils/directing";

const { mockGetMyScore, mockGetDirectingSummary } = vi.hoisted(() => ({
  mockGetMyScore: vi.fn(),
  mockGetDirectingSummary: vi.fn(),
}));

vi.mock("../api/product.js", () => ({
  getMyScore: mockGetMyScore,
  recalculateScore: vi.fn(),
  getScoreHistory: vi.fn().mockResolvedValue({ history: [] }),
  getThreeAxis: vi.fn().mockResolvedValue(null),
}));

vi.mock("../api/directing.js", () => ({ getDirectingSummary: mockGetDirectingSummary }));

const SCORE = {
  master_score: 61,
  kpis: { execution_speed: 60, decision_efficiency: 55, ai_productivity_boost: 50, focus_quality: 42,
          masterplan_progress: 70 },
  weights: { focus_quality: 0.15 },
};

const SUMMARY = {
  days: 7, in_score: false, daily: [],
  totals: { directing_minutes: 190, sessions: 6, prompts: 41, watcher_minutes: 120 },
};

beforeEach(() => {
  mockGetMyScore.mockResolvedValue(SCORE);
});

test("formats minutes and the line", () => {
  expect(fmtMinutes(190)).toBe("3 h 10 m");
  expect(fmtMinutes(45.4)).toBe("45 m");
  expect(directingNote(SUMMARY)).toBe(
    "Directing agents: 3 h 10 m over 6 sessions in the last 7 days (not in the score).",
  );
  expect(directingNote({ days: 7, totals: { directing_minutes: 3, sessions: 1, prompts: 1 } })).toContain("1 session ");
  expect(directingNote({ days: 7, totals: { directing_minutes: 0, sessions: 0, prompts: 0 } })).toBeNull();
  expect(directingNote(null)).toBeNull();
});

test("shows the line under Focus quality when there are prompts", async () => {
  mockGetDirectingSummary.mockResolvedValue(SUMMARY);
  render(<KPIDashboard />);
  const note = await screen.findByTestId("kpi-note");
  expect(note.textContent).toContain("3 h 10 m over 6 sessions");
  expect(note.textContent).toContain("not in the score");
  expect(mockGetDirectingSummary).toHaveBeenCalledWith(7, expect.anything());
});

test("shows nothing when the read fails", async () => {
  mockGetDirectingSummary.mockRejectedValue(new Error("down"));
  render(<KPIDashboard />);
  await waitFor(() => expect(screen.getByText("Focus Quality")).toBeTruthy());
  expect(screen.queryByTestId("kpi-note")).toBeNull();
});
