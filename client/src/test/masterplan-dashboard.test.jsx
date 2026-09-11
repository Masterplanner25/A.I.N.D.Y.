import { render, screen, fireEvent } from "@testing-library/react";

import { AppProviders } from "./utils";

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

import MasterPlanDashboard from "../components/app/MasterPlanDashboard";

describe("MasterPlanDashboard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockStartGenesisSession.mockReset();
    mockSendGenesisMessage.mockReset();
    mockSynthesizeGenesisDraft.mockReset();
    mockLockMasterPlan.mockReset();
    mockListMasterPlans.mockReset();
    mockActivateMasterPlan.mockReset();
    mockSetMasterplanAnchor.mockReset();
    mockGetMasterplanProjection.mockReset();

    mockListMasterPlans.mockResolvedValue({ plans: [] });
    mockActivateMasterPlan.mockResolvedValue({});
    mockSetMasterplanAnchor.mockResolvedValue({});
    mockGetMasterplanProjection.mockResolvedValue(null);
    mockGetStrategyLayer.mockResolvedValue({ phases: [] });
    mockGetPhaseAdvanceProposal.mockResolvedValue({ proposed: false, reason: "no_phases" });
    mockGetMasterPlan.mockResolvedValue({ id: 1, structure_json: null });
  });

  it("renders without crashing on mount", async () => {
    render(
      <AppProviders>
        <MasterPlanDashboard />
      </AppProviders>,
    );

    expect(screen.getByRole("heading", { name: /master plans/i })).toBeInTheDocument();
    expect(await screen.findByText(/no master plans yet\./i)).toBeInTheDocument();
  });

  it("shows loading state while plans are fetching", () => {
    mockListMasterPlans.mockReturnValue(new Promise(() => {}));

    render(
      <AppProviders>
        <MasterPlanDashboard />
      </AppProviders>,
    );

    expect(screen.getByText(/loading master plans/i)).toBeInTheDocument();
  });

  it("shows plans when they are returned", async () => {
    mockListMasterPlans.mockResolvedValue({
      plans: [
        {
          id: 7,
          version_label: "Plan Alpha",
          status: "locked",
          is_active: false,
        },
      ],
    });

    render(
      <AppProviders>
        <MasterPlanDashboard />
      </AppProviders>,
    );

    expect(await screen.findByText("Plan Alpha")).toBeInTheDocument();
  });

  it("shows empty state when no plans exist", async () => {
    render(
      <AppProviders>
        <MasterPlanDashboard />
      </AppProviders>,
    );

    expect(await screen.findByText(/no master plans yet\./i)).toBeInTheDocument();
    expect(screen.getByText(/create your first plan to begin tracking objectives/i)).toBeInTheDocument();
  });

  const ACTIVE_PLAN = {
    id: 7,
    version_label: "Plan Alpha",
    status: "active",
    is_active: true,
    posture: "Accelerated",
  };

  it("surfaces cascade execution metrics on the active plan", async () => {
    mockListMasterPlans.mockResolvedValue({ plans: [ACTIVE_PLAN] });
    mockGetMasterplanProjection.mockResolvedValue({
      velocity: 1.0,
      projected_completion_date: "2026-08-01",
      days_ahead_behind: 24,
      eta_confidence: "high",
      total_tasks: 3,
      completed_tasks: 1,
      remaining_tasks: 2,
      critical_depth: 6,
      blocked_tasks: 1,
      ready_tasks: 1,
      projection_basis: "cascade",
    });

    render(
      <AppProviders>
        <MasterPlanDashboard />
      </AppProviders>,
    );

    // dependency-aware basis chip + the new critical-chain / ready-blocked metrics
    expect(await screen.findByText("cascade")).toBeInTheDocument();
    expect(screen.getByText("6 deep")).toBeInTheDocument();
    expect(screen.getByText("1 ready · 1 blocked")).toBeInTheDocument();
    // existing metric still renders
    expect(screen.getByText("24d ahead")).toBeInTheDocument();
  });

  it("omits the cascade chip and critical chain on the velocity fallback", async () => {
    mockListMasterPlans.mockResolvedValue({ plans: [ACTIVE_PLAN] });
    mockGetMasterplanProjection.mockResolvedValue({
      velocity: 0.5,
      projected_completion_date: "2026-09-01",
      days_ahead_behind: -3,
      eta_confidence: "medium",
      total_tasks: 10,
      completed_tasks: 4,
      remaining_tasks: 6,
      critical_depth: 0,
      blocked_tasks: 0,
      ready_tasks: 0,
      projection_basis: "velocity",
    });

    render(
      <AppProviders>
        <MasterPlanDashboard />
      </AppProviders>,
    );

    expect(await screen.findByText("3d behind")).toBeInTheDocument();
    expect(screen.queryByText("cascade")).not.toBeInTheDocument();
    expect(screen.queryByText(/deep/)).not.toBeInTheDocument();
  });

  it("surfaces continuous-time effort metrics on the duration basis", async () => {
    mockListMasterPlans.mockResolvedValue({ plans: [ACTIVE_PLAN] });
    mockGetMasterplanProjection.mockResolvedValue({
      velocity: 1.0,
      projected_completion_date: "2026-08-15",
      days_ahead_behind: 12,
      eta_confidence: "high",
      total_tasks: 3,
      completed_tasks: 1,
      remaining_tasks: 2,
      critical_depth: 2,
      blocked_tasks: 0,
      ready_tasks: 2,
      remaining_effort: 34,
      critical_path_effort: 20,
      work_velocity: 10,
      projection_basis: "duration",
    });

    render(
      <AppProviders>
        <MasterPlanDashboard />
      </AppProviders>,
    );

    // duration basis shows its own chip + the effort-left line
    expect(await screen.findByText("duration")).toBeInTheDocument();
    expect(screen.getByText("~34h")).toBeInTheDocument();
    expect(screen.getByText("12d ahead")).toBeInTheDocument();
  });

  it("VIEW PLAN shows the plan itself — the words, not just the metadata", async () => {
    mockListMasterPlans.mockResolvedValue({
      plans: [{ id: 10, version_label: "V1", status: "locked", is_active: true }],
    });
    mockGetMasterPlan.mockResolvedValue({
      id: 10,
      structure_json: {
        vision_statement: "To architect a durable, AI-native ecosystem.",
        primary_mechanism: "Develop a framework for ethical AI.",
        time_horizon_years: 5,
        core_domains: [{ name: "Ethical AI Framework", intent: "To establish guidelines." }],
        success_criteria: ["Establishment of a widely adopted ethical AI framework"],
        key_assets: ["Nodus (orchestration DSL)"],
        risk_factors: ["Funding constraints"],
        synthesis_notes: "The synthesis process was confident.",
      },
    });

    render(
      <AppProviders>
        <MasterPlanDashboard />
      </AppProviders>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /view plan/i }));

    const detail = await screen.findByTestId("plan-detail");
    expect(mockGetMasterPlan).toHaveBeenCalledWith(10);
    expect(detail).toHaveTextContent("To architect a durable, AI-native ecosystem.");
    expect(detail).toHaveTextContent("Ethical AI Framework");
    expect(detail).toHaveTextContent("To establish guidelines.");
    expect(detail).toHaveTextContent("Nodus (orchestration DSL)");
    expect(detail).toHaveTextContent("Funding constraints");
    expect(detail).toHaveTextContent("5 years");

    fireEvent.click(screen.getByRole("button", { name: /hide plan/i }));
    expect(screen.queryByTestId("plan-detail")).not.toBeInTheDocument();
  });
});
