import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock the operator API before importing the component.
vi.mock("../api/operator.js", () => ({
  getQueueHealth: vi.fn(),
  getDeadLetters: vi.fn(),
  replayDeadLetter: vi.fn(),
  deleteDeadLetter: vi.fn(),
  drainDeadLetters: vi.fn(),
}));

import DeadLetterQueuePanel from "../components/platform/DeadLetterQueuePanel";
import {
  getQueueHealth,
  getDeadLetters,
  replayDeadLetter,
  deleteDeadLetter,
  drainDeadLetters,
} from "../api/operator.js";

const ITEM = {
  job_id: "job-1",
  task_name: "send_email",
  retry_metadata: { attempt_count: 3, max_attempts: 3 },
  enqueued_at: "2026-07-31T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  getQueueHealth.mockResolvedValue({ backend_name: "redis", degraded: false, metrics: { dlq_depth: 1, queue_depth: 0, in_flight_count: 0 } });
  getDeadLetters.mockResolvedValue({ count: 1, items: [ITEM], backend: "redis" });
  replayDeadLetter.mockResolvedValue({ replayed: true, job_id: "job-1" });
  deleteDeadLetter.mockResolvedValue({ removed: true, job_id: "job-1" });
  drainDeadLetters.mockResolvedValue({ drained: 1 });
});

describe("DeadLetterQueuePanel", () => {
  it("renders a dead-letter job after load", async () => {
    render(<DeadLetterQueuePanel />);
    expect(await screen.findByText("send_email")).toBeInTheDocument();
    expect(screen.getByText("job-1")).toBeInTheDocument();
    expect(screen.getByText(/3\/3 attempts/)).toBeInTheDocument();
  });

  it("replays a job and reloads the queue", async () => {
    render(<DeadLetterQueuePanel />);
    await screen.findByText("send_email");
    fireEvent.click(screen.getByRole("button", { name: "Replay" }));
    await waitFor(() => expect(replayDeadLetter).toHaveBeenCalledWith("job-1"));
    // load() runs once on mount and again after the action.
    await waitFor(() => expect(getDeadLetters).toHaveBeenCalledTimes(2));
  });

  it("requires a confirm before deleting", async () => {
    render(<DeadLetterQueuePanel />);
    await screen.findByText("send_email");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    // First click reveals Confirm; it must not delete yet.
    expect(deleteDeadLetter).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(deleteDeadLetter).toHaveBeenCalledWith("job-1"));
  });

  it("requires a confirm before draining the whole queue", async () => {
    render(<DeadLetterQueuePanel />);
    await screen.findByText("send_email");
    fireEvent.click(screen.getByRole("button", { name: "Drain DLQ" }));
    expect(drainDeadLetters).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(drainDeadLetters).toHaveBeenCalled());
  });

  it("shows an empty state when the queue is clear", async () => {
    getDeadLetters.mockResolvedValue({ count: 0, items: [], backend: "redis" });
    render(<DeadLetterQueuePanel />);
    expect(await screen.findByText(/dead-letter queue is empty/i)).toBeInTheDocument();
  });
});
