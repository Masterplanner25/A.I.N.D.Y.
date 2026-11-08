import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it, beforeEach, vi } from "vitest";

vi.mock("../_core.js", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    authRequest: vi.fn(),
    adminRequest: vi.fn(),
  };
});

import { adminRequest, authRequest } from "../_core.js";
import * as operatorApi from "../operator.js";
import * as platformApi from "../platform.js";
import * as barrelApi from "../../api.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

describe("client API ownership boundaries", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("routes operator APIs through operator-owned endpoints", () => {
    operatorApi.getFlowRuns("waiting", "agent", 10);
    operatorApi.getSchedulerStatus();
    operatorApi.getObservabilityDashboard(12);

    expect(adminRequest).toHaveBeenNthCalledWith(
      1,
      "/platform/flows/runs?status=waiting&workflow_type=agent&limit=10",
      { method: "GET" },
    );
    expect(adminRequest).toHaveBeenNthCalledWith(
      2,
      "/platform/observability/scheduler/status",
      { method: "GET" },
    );
    expect(adminRequest).toHaveBeenNthCalledWith(
      3,
      "/platform/observability/dashboard?window_hours=12",
      { method: "GET" },
    );
  });

  it("routes platform UI APIs through the platform module", () => {
    platformApi.getDashboardOverview();
    platformApi.getHealthDetails();

    // PLATFORM is a mixed domain map: /dashboard/overview is app-domain (so it carries the
    // /apps mount), while /health/details is runtime-owned and does not.
    expect(authRequest).toHaveBeenNthCalledWith(1, "/apps/dashboard/overview", { method: "GET" });
    expect(authRequest).toHaveBeenNthCalledWith(2, "/health/details", { method: "GET" });
  });

  it("exposes platform UI calls from platform.js alongside operator re-exports", () => {
    expect(platformApi.getFlowRuns).toBeTypeOf("function");
    expect(platformApi.getObservabilityDashboard).toBeTypeOf("function");
    expect(platformApi.getDashboardOverview).toBeTypeOf("function");
    expect(platformApi.getHealthDetails).toBeTypeOf("function");
  });

  it("no longer exports the wrappers for RippleTrace's retired legacy routes", () => {
    // Retired server-side in #548; the graph view uses ./rippletrace.js.
    expect(platformApi.getInfluenceGraph).toBeUndefined();
    expect(platformApi.getCausalGraph).toBeUndefined();
    expect(platformApi.getNarrative).toBeUndefined();
  });

  it("preserves backward-compatible flat exports while exposing explicit categories", () => {
    expect(barrelApi.getMyScore).toBeTypeOf("function");
    expect(barrelApi.getFlowRuns).toBeTypeOf("function");
    expect(barrelApi.getDashboardOverview).toBeTypeOf("function");
    expect(barrelApi.productApi.getMyScore).toBeTypeOf("function");
    expect(barrelApi.operatorApi.getFlowRuns).toBeTypeOf("function");
    expect(barrelApi.legacyApi).toBeUndefined();
  });

  it("uses explicit API categories in the focused UI components", () => {
    const dashboardSource = readFileSync(resolve(__dirname, "../../components/app/Dashboard.jsx"), "utf8");
    const graphViewSource = readFileSync(resolve(__dirname, "../../components/app/GraphView.jsx"), "utf8");
    const flowConsoleSource = readFileSync(resolve(__dirname, "../../components/platform/FlowEngineConsole.jsx"), "utf8");
    const observabilitySource = readFileSync(
      resolve(__dirname, "../../components/platform/ObservabilityDashboard.jsx"),
      "utf8",
    );
    const healthSource = readFileSync(resolve(__dirname, "../../components/platform/HealthDashboard.jsx"), "utf8");

    expect(dashboardSource).toContain('from "../../api/platform.js"');
    expect(dashboardSource).toContain('from "../../api/product.js"');
    // GraphView pulls graph data from the canonical, user-authable rippletrace routes — NOT
    // platform.js's legacy api-key-gated getInfluenceGraph/getCausalGraph, which 401 a normal
    // user and trip the global session-expired logout.
    expect(graphViewSource).toContain('from "../../api/rippletrace.js"');
    expect(graphViewSource).not.toContain('getInfluenceGraph } from "../../api/platform.js"');
    expect(flowConsoleSource).toContain('from "../../api/operator.js"');
    expect(observabilitySource).toContain('from "../../api/operator.js"');
    expect(healthSource).toContain('from "../../api/platform.js"');
  });

  it("uses explicit API categories in core data-fetching components", () => {
    const taskSource = readFileSync(resolve(__dirname, "../../components/app/TaskDashboard.jsx"), "utf8");
    const armSource = readFileSync(resolve(__dirname, "../../components/app/ARMAnalyze.jsx"), "utf8");
    const agentSource = readFileSync(resolve(__dirname, "../../components/platform/AgentConsole.jsx"), "utf8");

    expect(taskSource).not.toContain('from "../../api"');
    expect(taskSource).toContain('from "../../api/tasks.js"');
    expect(armSource).not.toContain('from "../../api"');
    expect(armSource).toContain('from "../../api/arm.js"');
    expect(agentSource).not.toContain('from "../../api"');
    expect(agentSource).toContain('from "../../api/agent.js"');
  });
});
