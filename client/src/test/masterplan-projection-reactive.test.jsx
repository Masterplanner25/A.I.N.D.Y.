import { fireEvent, render, screen } from "@testing-library/react";

import { AppProviders } from "./utils";
import { MasterplanProjectionProvider } from "../context/MasterplanProjectionContext.jsx";

const { mockGetTasks, mockCreateTask, mockCompleteTask, mockStartTask } =
  vi.hoisted(() => ({
    mockGetTasks: vi.fn(),
    mockCreateTask: vi.fn(),
    mockCompleteTask: vi.fn(),
    mockStartTask: vi.fn(),
  }));

const {
  mockStartGenesisSession,
  mockSendGenesisMessage,
  mockSynthesizeGenesisDraft,
  mockLockMasterPlan,
  mockListMasterPlans,
  mockActivateMasterPlan,
  mockSetMasterplanAnchor,
  mockGetMasterplanProjection,
  mockGetStrategyLayer,
  mockGetPhaseAdvanceProposal,
  mockConfirmPhaseAdvance,
  mockDismissPhaseAdvance,
  mockReopenPhase,
  mockGetMasterPlan,
} = vi.hoisted(() => ({
  mockStartGenesisSession: vi.fn(),
  mockSendGenesisMessage: vi.fn(),
  mockSynthesizeGenesisDraft: vi.fn(),
  mockLockMasterPlan: vi.fn(),
  mockListMasterPlans: vi.fn(),
  mockActivateMasterPlan: vi.fn(),
  mockSetMasterplanAnchor: vi.fn(),
  mockGetMasterplanProjection: vi.fn(),
  mockGetStrategyLayer: vi.fn(),
  mockGetPhaseAdvanceProposal: vi.fn(),
  mockConfirmPhaseAdvance: vi.fn(),
  mockDismissPhaseAdvance: vi.fn(),
  mockReopenPhase: vi.fn(),
  mockGetMasterPlan: vi.fn(),
}));

vi.mock("../api/tasks.js", () => ({
  getTasks: mockGetTasks,
  createTask: mockCreateTask,
  completeTask: mockCompleteTask,
  startTask: mockStartTask,
}));

vi.mock("../api/masterplan.js", () => ({
  startGenesisSession: mockStartGenesisSession,
  sendGenesisMessage: mockSendGenesisMessage,
  synthesizeGenesisDraft: mockSynthesizeGenesisDraft,
  lockMasterPlan: mockLockMasterPlan,
  listMasterPlans: mockListMasterPlans,
  activateMasterPlan: mockActivateMasterPlan,
  setMasterplanAnchor: mockSetMasterplanAnchor,
  getMasterplanProjection: mockGetMasterplanProjection,
  getStrategyLayer: mockGetStrategyLayer,
  getPhaseAdvanceProposal: mockGetPhaseAdvanceProposal,
  confirmPhaseAdvance: mockConfirmPhaseAdvance,
  dismissPhaseAdvance: mockDismissPhaseAdvance,
  reopenPhase: mockReopenPhase,
  getMasterPlan: mockGetMasterPlan,
}));

import TaskDashboard from "../components/app/TaskDashboard";
import MasterPlanDashboard from "../components/app/MasterPlanDashboard";

const ACTIVE_PLAN = {
  id: 7,
  version_label: "Plan Alpha",
  status: "active",
  is_active: true,
};

// Stale projection served by the plan panel's own fetch on mount.
const STALE_PROJECTION = {
  velocity: 0.8,
  projected_completion_date: "2026-09-01",
  days_ahead_behind: 5,
  eta_confidence: "medium",
  total_tasks: 4,
  completed_tasks: 1,
  remaining_tasks: 3,
  projection_basis: "velocity",
};

// Fresh, cascade-aware projection returned in the /tasks/complete response.
const FRESH_PROJECTION = {
  velocity: 1.0,
  projected_completion_date: "2026-08-01",
  days_ahead_behind: 20,
  eta_confidence: "high",
  total_tasks: 4,
  completed_tasks: 2,
  remaining_tasks: 2,
  critical_depth: 4,
  blocked_tasks: 0,
  ready_tasks: 2,
  projection_basis: "cascade",
};

function renderSurfaces() {
  return render(
    <AppProviders>
      <MasterplanProjectionProvider>
        <TaskDashboard />
        <MasterPlanDashboard />
      </MasterplanProjectionProvider>
    </AppProviders>,
  );
}

/**
 * Completing became a two-step interaction on 2026-09-07: "Done" opens an inline judgement
 * step (complexity + difficulty, 1-5) and "Complete task" sends the request. Both feed WCU,
 * which was reduced to estimated hours while nothing collected them.
 *
 * These tests are about the PROJECTION reacting to a completion, not about the judgement, so
 * this helper drives the new steps and keeps their subject unchanged.
 */
const completeTaskFromUI = () => {
  fireEvent.click(screen.getByRole("button", { name: /done/i }));
  fireEvent.click(screen.getByRole("button", { name: "Complexity 3 of 5" }));
  fireEvent.click(screen.getByRole("button", { name: "Difficulty 3 of 5" }));
  fireEvent.click(screen.getByRole("button", { name: /Complete task/i }));
};

describe("MasterPlan projection reacts to task completion", () => {
  beforeEach(() => {
    mockGetTasks.mockReset();
    mockCreateTask.mockReset();
    mockCompleteTask.mockReset();
    mockStartTask.mockReset();
    mockListMasterPlans.mockReset();
    mockActivateMasterPlan.mockReset();
    mockSetMasterplanAnchor.mockReset();
    mockGetMasterplanProjection.mockReset();

    mockGetTasks.mockResolvedValue([
      { task_name: "Ship v1", status: "pending", time_spent: 0 },
    ]);
    mockListMasterPlans.mockResolvedValue({ plans: [ACTIVE_PLAN] });
    mockActivateMasterPlan.mockResolvedValue({});
    mockSetMasterplanAnchor.mockResolvedValue({});
    mockGetMasterplanProjection.mockResolvedValue(STALE_PROJECTION);
    mockGetStrategyLayer.mockResolvedValue({ phases: [] });
    mockGetPhaseAdvanceProposal.mockResolvedValue({ proposed: false, reason: "no_phases" });
  });

  it("adopts the completion-response projection without a refetch", async () => {
    // Completion returns the recomputed projection under `orchestration`
    // (the task_completion flow's result extractor).
    mockCompleteTask.mockResolvedValue({
      task_result: "Task 'Ship v1' completed.",
      orchestration: {
        masterplan_id: 7,
        masterplan_projection: FRESH_PROJECTION,
        eta_recalculated: true,
      },
    });

    renderSurfaces();

    // Panel starts on its own (stale, velocity-basis) fetch.
    expect(await screen.findByText("5d ahead")).toBeInTheDocument();
    expect(screen.queryByText("cascade")).not.toBeInTheDocument();

    // Complete the task from the task surface.
    completeTaskFromUI();

    // The plan panel adopts the fresh cascade projection reactively — no
    // second getMasterplanProjection call is made.
    expect(await screen.findByText("20d ahead")).toBeInTheDocument();
    expect(screen.getByText("cascade")).toBeInTheDocument();
    expect(screen.getByText("4 deep")).toBeInTheDocument();
    expect(mockGetMasterplanProjection).toHaveBeenCalledTimes(1);
  });

  it("leaves the panel untouched when completion carries no reprojection", async () => {
    mockCompleteTask.mockResolvedValue({
      task_result: "Task 'Ship v1' completed.",
      orchestration: { masterplan_id: null, masterplan_projection: null },
    });

    renderSurfaces();

    expect(await screen.findByText("5d ahead")).toBeInTheDocument();

    completeTaskFromUI();

    // Still the original projection; nothing published.
    expect(await screen.findByText("5d ahead")).toBeInTheDocument();
    expect(screen.queryByText("cascade")).not.toBeInTheDocument();
  });
});
