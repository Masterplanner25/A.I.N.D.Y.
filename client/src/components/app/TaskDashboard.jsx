import React, { useCallback, useEffect, useMemo, useState } from "react";
import { getTasks, createTask, completeTask, startTask, deleteTask } from "../../api/tasks.js";
import { listMasterPlans, getStrategyLayer, promoteTaskToStrategy } from "../../api/masterplan.js";
import { Toast } from "../shared/Toast";
import DomainError from "../shared/DomainError.jsx";
import { safeMap } from "../../utils/safe";
import { EFFORT_UNITS, toHours, describeHours } from "../../utils/effort.js";
import { useToast } from "../../utils/useToast";
import { useApiCall } from "../../lib/useApiCall.js";
import {
  useMasterplanProjection,
  extractReprojection,
} from "../../context/MasterplanProjectionContext.jsx";

export default function TaskDashboard() {
  const [newTask, setNewTask] = useState("");
  // `estimated_hours` lands in Task.duration, which is the effort term the MasterPlan
  // ETA projects against AND the input to the Infinity Volume axis. The form used to
  // send only {name, priority}, so duration was always 0 — every three-axis shadow
  // record came back with volume_score = 0 regardless of how much work was completed.
  const [estimatedHours, setEstimatedHours] = useState("");
  // The unit the estimate is typed in. Stored as hours (the math's unit) — see effort.js.
  // A months-long "task" is usually a strategy wearing a task row (STRATEGY_LAYER_SPEC §3),
  // but the entry should not be the thing that makes that hard to say.
  const [effortUnit, setEffortUnit] = useState("hours");
  // Task.masterplan_id drives ETA/WCU recalculation and the completion cascade. It was
  // reachable by the API and by agent tools but never set from this screen, so every
  // task created in the UI was permanently orphaned from every plan (walk-log item 17).
  const [masterplanId, setMasterplanId] = useState("");
  const [plans, setPlans] = useState([]);
  // Which phase of the plan the task belongs to. Empty means "the plan's current phase" —
  // the API resolves it — so a task is never created invisible to the strategy layer, which
  // is what every task from this screen used to be (phase_id = NULL, so it neither counted
  // toward a phase nor brought a dismissed advance proposal back).
  const [phaseId, setPhaseId] = useState("");
  const [phases, setPhases] = useState([]);
  // Which strategy the task serves. A task under a strategy is scheduled where the strategy
  // is, so picking one overrides the phase. A months-long "task" is a strategy wearing a task
  // row (STRATEGY_LAYER_SPEC §3); the ↑ STRATEGY button on each task is how it stops being one.
  const [strategyId, setStrategyId] = useState("");
  const [strategies, setStrategies] = useState([]);
  const [strategyVersion, setStrategyVersion] = useState(0);
  const [promoting, setPromoting] = useState(() => new Set());
  const [velocityMessage, setVelocityMessage] = useState("");
  // Names of tasks with a completion request in flight. Completing a task runs the whole
  // `task_completion` flow — memory capture, downstream unlock, ETA recalc and a full
  // Infinity re-score — which took ~14s on the live stack, and until then this screen gave
  // no sign the click had registered: no disabled state, no spinner, and `velocityMessage`
  // is only set *after* the await resolves. So the button invited re-clicking.
  //
  // Measured 2026-09-06: one completion arrived at the API as 4 `tasks.complete` calls,
  // producing 4 flow runs and duplicate score_history / three_axis_shadow_records rows.
  // The server now refuses to re-orchestrate a repeat (task_orchestrate's guard), so this
  // is the second of two layers — it stops the requests being sent at all, and gives the
  // user the feedback whose absence caused the re-clicking.
  const [completing, setCompleting] = useState(() => new Set());
  // True while a create request is in flight. Creation round-trips through the API and the
  // list only repaints after `fetchTasks()` resolves, so ADD appears to do nothing for a
  // moment — which invites a second press and creates a duplicate task.
  const [creating, setCreating] = useState(false);
  // Names with a delete request in flight — same single-flight reasoning as `completing`.
  const [deleting, setDeleting] = useState(() => new Set());
  // The task whose completion judgement is being taken, and the two 1-5 values so far.
  // Collected at COMPLETION rather than creation: difficulty guessed up front is a guess,
  // difficulty recorded afterwards is an observation — and WCU only accrues from completed
  // tasks, so nothing is lost by waiting. Both feed `effort x complexity x difficulty`, and
  // both were permanently 1 because nothing ever set them.
  const [judging, setJudging] = useState(null);
  const [judgement, setJudgement] = useState({ complexity: null, difficulty: null });
  const { toast, showToast, clearToast } = useToast();
  const { publishProjection } = useMasterplanProjection();
  const { loading, error, data, execute: fetchTasks } = useApiCall(getTasks, {
    domain: "tasks",
  });

  const tasks = useMemo(() => {
    const items = Array.isArray(data) ? [...data] : [];
    return items.sort((a) => (a.status === "completed" ? 1 : -1));
  }, [data]);

  // Every strategy on every listed plan, by id, so the list can group tasks under the
  // strategy they serve. A task's strategy is on the task's plan, not necessarily the one
  // the form is pointed at, so this is separate from the form's picker state.
  //
  // The owner's first reaction to promotion was "all of it disappeared": the promoted rows
  // left this list and became strategies on the plan card, with nothing here to say so.
  // Grouping is the answer — a task's strategy is visible where the task is.
  const [strategyIndex, setStrategyIndex] = useState({});
  useEffect(() => {
    if (plans.length === 0) return undefined;
    let cancelled = false;
    Promise.all(safeMap(plans, (plan) => getStrategyLayer(plan.id).catch(() => null)))
      .then((layers) => {
        if (cancelled) return;
        const index = {};
        layers.forEach((layer) => {
          if (!layer) return;
          const phaseName = {};
          (layer.phases || []).forEach((ph) => { phaseName[ph.id] = ph.name; });
          (layer.strategies || []).forEach((st) => {
            index[st.id] = { id: st.id, name: st.name, status: st.status, phaseName: phaseName[st.phase_id] || null };
          });
        });
        setStrategyIndex(index);
      });
    return () => { cancelled = true; };
  }, [plans, strategyVersion]);

  // Tasks grouped by strategy, strategies in order of first appearance, then everything
  // with no strategy. Plan tasks with no strategy and plan-less tasks share the last group:
  // neither serves an approach, and that is the fact worth seeing.
  const groups = useMemo(() => {
    const byStrategy = new Map();
    const none = [];
    tasks.forEach((task) => {
      const sid = task.strategy_id;
      if (sid) {
        if (!byStrategy.has(sid)) byStrategy.set(sid, []);
        byStrategy.get(sid).push(task);
      } else {
        none.push(task);
      }
    });
    const out = [];
    byStrategy.forEach((list, sid) => {
      const strategy = strategyIndex[sid] || { id: sid, name: "(strategy)", phaseName: null };
      out.push({
        key: `s:${sid}`, label: `Strategy ${strategy.name}`, strategy, tasks: list,
        done: list.filter((t) => t.status === "completed").length,
      });
    });
    if (none.length > 0) out.push({ key: "none", label: "Tasks with no strategy", strategy: null, tasks: none, done: 0 });
    return out;
  }, [tasks, strategyIndex]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  // The plan picker is additive: if plans can't be listed (or none exist — creation is
  // Genesis-only today) the selector simply doesn't render and task creation is unaffected.
  // The plan's phases and open strategies, for the pickers. Reloaded when the plan changes
  // AND after a promotion — a strategy made from this screen has to be offerable from this
  // screen without leaving it, which it was not on 2026-09-10 (the layer was fetched once,
  // on plan selection, and the ↑ Strategy button never refetched it).
  const loadLayer = useCallback(async (planId) => {
    if (!planId) { setPhases([]); setStrategies([]); return; }
    try {
      const layer = await getStrategyLayer(planId);
      setPhases(Array.isArray(layer?.phases) ? layer.phases : []);
      // Only strategies still open can take new work.
      setStrategies((Array.isArray(layer?.strategies) ? layer.strategies : [])
        .filter((st) => st.status === "proposed" || st.status === "active"));
    } catch {
      setPhases([]);
      setStrategies([]);
    }
  }, []);

  useEffect(() => {
    setPhaseId("");
    setStrategyId("");
    loadLayer(masterplanId);
  }, [masterplanId, loadLayer]);

  useEffect(() => {
    let cancelled = false;
    listMasterPlans()
      .then((data) => {
        if (!cancelled) setPlans(Array.isArray(data?.plans) ? data.plans : []);
      })
      .catch(() => {
        if (!cancelled) setPlans([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!newTask.trim()) return;

    // ★ The estimate is REQUIRED, not optional. It lands in `Task.duration`, which is
    // load-bearing for three separate things: the MasterPlan ETA's effort projection, the
    // Infinity Volume axis (which SUMS duration), and the Trajectory axis (which does
    // `if est_hours <= 0: continue` — a task with no estimate is skipped outright).
    //
    // Leaving it optional was a data-loss default dressed as convenience. Measured
    // 2026-09-06: a task completed with a blank estimate moved `completed_count` 1 -> 2 and
    // left `effort_hours`, `volume_score`, `trajectory_score` and `mean_pace_ratio` byte-
    // identical. Real work was done and two of the three axes did not register it — the
    // exact measurement SOAK-THEN-FLIP-1 is blocked on.
    const hours = toHours(estimatedHours, effortUnit);
    if (!Number.isFinite(hours) || hours <= 0) {
      showToast("An estimate is required — a task without one is invisible to scoring.");
      return;
    }

    // Single-flight, same reasoning as `handleComplete`: creation round-trips through the
    // API and the list only refreshes after `fetchTasks()`, so there is a window where a
    // submitted task is not on screen yet. Without this the obvious response — press ADD
    // again — created a duplicate. It did, on 2026-09-06: tasks 18 and 19, same name.
    if (creating) return;
    setCreating(true);

    try {
      // `masterplan_id` stays optional — the API treats it as Optional and an explicit
      // null is not the same as omitting it.
      const payload = { name: newTask, priority: "medium", estimated_hours: hours };
      if (masterplanId) payload.masterplan_id = Number.parseInt(masterplanId, 10);
      if (masterplanId && phaseId) payload.phase_id = phaseId;
      if (masterplanId && strategyId) payload.strategy_id = strategyId;

      await createTask(payload);
      setNewTask("");
      setEstimatedHours("");
      fetchTasks();
    } catch (err) {
      showToast(err?.message || "Failed to create task. Please try again.");
    } finally {
      // `finally`, so a failed create can be retried — only an in-flight submit is blocked.
      setCreating(false);
    }
  };

  const handlePromote = async (task) => {
    // The task row goes and a strategy takes its place on the same phase; the estimate is
    // kept in the strategy's description. Irreversible in the sense that the task is gone,
    // so it is confirmed. A completed task cannot be promoted — it was work.
    if (!task.masterplan_id || !task.task_id) return;
    if (!window.confirm(`Make "${task.task_name}" a strategy of its phase? The task row is replaced.`)) return;
    setPromoting((prev) => new Set(prev).add(task.task_name));
    try {
      const result = await promoteTaskToStrategy(task.masterplan_id, task.task_id);
      setVelocityMessage(`"${result?.strategy?.name || task.task_name}" is now a strategy. Add the tasks that make it happen under it.`);
      fetchTasks();
      setStrategyVersion((v) => v + 1);
      // The new strategy must be in the picker now, not after a page reload. If the form is
      // pointed at another plan (or none), the effect above reloads when it changes anyway.
      if (String(task.masterplan_id) === String(masterplanId)) {
        await loadLayer(masterplanId);
      } else {
        setMasterplanId(String(task.masterplan_id));
      }
    } catch (err) {
      showToast(err?.message || "Could not promote the task.");
    } finally {
      setPromoting((prev) => { const next = new Set(prev); next.delete(task.task_name); return next; });
    }
  };

  const handleDelete = async (taskName) => {
    // Deletion is irreversible and there is no undo, so it is confirmed rather than
    // single-click. Every other action here is recoverable; this one is not.
    if (!window.confirm(`Delete "${taskName}"? This cannot be undone.`)) return;

    let alreadyInFlight = false;
    setDeleting((prev) => {
      if (prev.has(taskName)) {
        alreadyInFlight = true;
        return prev;
      }
      const next = new Set(prev);
      next.add(taskName);
      return next;
    });
    if (alreadyInFlight) return;

    try {
      await deleteTask(taskName);
      fetchTasks();
    } catch (err) {
      showToast(err?.message || "Failed to delete task. Please try again.");
    } finally {
      setDeleting((prev) => {
        if (!prev.has(taskName)) return prev;
        const next = new Set(prev);
        next.delete(taskName);
        return next;
      });
    }
  };

  const openJudgement = (taskName) => {
    setJudging(taskName);
    // Deliberately no defaults. Pre-selecting a middle value would record a fabricated
    // judgement for anyone who just clicks through — the same failure the worth-declaration
    // spec is built around, and the reason these columns being 1 was so hard to notice.
    setJudgement({ complexity: null, difficulty: null });
  };

  const cancelJudgement = () => {
    setJudging(null);
    setJudgement({ complexity: null, difficulty: null });
  };

  const handleComplete = async (taskName, values = {}) => {
    // Functional update + read-back: two clicks in the same tick would both see a stale
    // `completing` from the closure and both pass a plain `.has()` check.
    let alreadyInFlight = false;
    setCompleting((prev) => {
      if (prev.has(taskName)) {
        alreadyInFlight = true;
        return prev;
      }
      const next = new Set(prev);
      next.add(taskName);
      return next;
    });
    if (alreadyInFlight) return;

    try {
      const res = await completeTask(taskName, values);
      cancelJudgement();

      // Push the recomputed cascade-aware MasterPlan projection to the shared
      // context so the MasterPlan surface reflects it without waiting for its
      // own refetch (MASTERPLAN_SAAS Step 2/3).
      const reproj = extractReprojection(res);
      if (reproj) publishProjection(reproj.planId, reproj.projection);

      // Show the backend confirmation (contains TWR score). Render a string
      // regardless of the response envelope shape.
      const message =
        typeof res === "string"
          ? res
          : res?.task_result || res?.message || "Task completed.";
      setVelocityMessage(message);
      fetchTasks();

      // Clear message after 3s
      setTimeout(() => setVelocityMessage(""), 5000);
    } catch (err) {
      showToast(err?.message || "Failed to complete task. Please try again.");
    } finally {
      // `finally`, so a failed completion re-enables the button — the user must be able
      // to retry a genuine failure. Only an in-flight request is blocked, never a retry.
      setCompleting((prev) => {
        if (!prev.has(taskName)) return prev;
        const next = new Set(prev);
        next.delete(taskName);
        return next;
      });
    }
  };

  const handleStart = async (taskName) => {
    await startTask(taskName);
    fetchTasks();
  };

  return (
    <div style={styles.container}>
      <h2 style={styles.title}>🚀 Execution Engine</h2>
      
      {/* --- VELOCITY FEEDBACK --- */}
      {velocityMessage &&
      <div style={styles.successBanner}>
          {velocityMessage}
        </div>
      }

      {/* --- INPUT --- */}
      <form onSubmit={handleCreate} style={styles.form}>
        <div style={styles.formRow}>
          <input
            style={styles.input}
            placeholder="Initialize new directive..."
            value={newTask}
            onChange={(e) => setNewTask(e.target.value)} />

          <button
            type="submit"
            disabled={creating}
            aria-busy={creating}
            style={{
              ...styles.addButton,
              ...(creating ? { opacity: 0.6, cursor: "progress" } : null),
            }}
          >
            {creating ? "ADDING…" : "ADD"}
          </button>
        </div>

        <div style={styles.formRow}>
          <label style={styles.fieldLabel}>
            Estimate *
            <span style={{ display: "inline-flex", gap: "6px" }}>
              <input
                style={styles.smallInput}
                type="number"
                min="0.25"
                step="0.25"
                required
                aria-required="true"
                placeholder="e.g. 1.5"
                title="Required — tasks without an estimate are excluded from Volume and Trajectory scoring"
                value={estimatedHours}
                onChange={(e) => setEstimatedHours(e.target.value)} />
              <select
                aria-label="Estimate unit"
                style={styles.select}
                value={effortUnit}
                onChange={(e) => setEffortUnit(e.target.value)}
                title="8h day, 5-day week, ~21.7 working days a month">
                {safeMap(EFFORT_UNITS, (u) => <option key={u.key} value={u.key}>{u.label}</option>)}
              </select>
            </span>
            {effortUnit !== "hours" && toHours(estimatedHours, effortUnit) > 0 &&
              <span style={{ fontSize: "11px", color: "#71717a", marginLeft: "6px" }}>
                = {toHours(estimatedHours, effortUnit)}h
              </span>
            }
          </label>

          {plans.length > 0 &&
          <label style={styles.fieldLabel}>
              MasterPlan
              <select
              style={styles.select}
              value={masterplanId}
              onChange={(e) => setMasterplanId(e.target.value)}>
                <option value="">— none —</option>
                {safeMap(plans, (plan) =>
              <option key={plan.id} value={plan.id}>
                    {plan.version_label || `Plan ${plan.id}`}
                    {plan.is_active ? " (active)" : ""}
                  </option>)
              }
              </select>
            </label>
          }

          {masterplanId && phases.length > 0 &&
          <label style={styles.fieldLabel}>
              Phase
              <select
              style={styles.select}
              value={phaseId}
              onChange={(e) => setPhaseId(e.target.value)}
              title="Leave on 'current phase' and the plan decides">
                <option value="">— current phase —</option>
                {safeMap(phases, (phase) =>
              <option key={phase.id} value={phase.id}>
                    {phase.ordinal}. {phase.name}{phase.status === "complete" ? " (complete)" : ""}
                  </option>)
              }
              </select>
            </label>
          }

          {masterplanId && strategies.length > 0 &&
          <label style={styles.fieldLabel}>
              Strategy
              <select
              style={styles.select}
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              title="A task under a strategy is scheduled where the strategy is">
                <option value="">— none —</option>
                {safeMap(strategies, (st) =>
              <option key={st.id} value={st.id}>{st.name}</option>)
              }
              </select>
            </label>
          }
        </div>

        <p style={styles.formHint}>
          The estimate feeds the MasterPlan ETA and the Infinity Volume axis. It is stored in
          hours (8h day, 5-day week, ~21.7 working days a month). Something that takes months
          is usually a strategy, not a task.
        </p>
      </form>

      {/* --- TASK LIST --- */}
      <div style={styles.list}>
        <DomainError domain="tasks" error={error} onRetry={fetchTasks} />
        {loading ? <p>Syncing...</p> : safeMap(groups, (group) =>
        <section key={group.key} aria-label={group.label} style={group.strategy ? styles.strategyGroup : undefined}>
            {group.strategy &&
          <div style={styles.strategyHeader} data-testid="strategy-group">
                <span style={{ fontSize: "10px", color: "#71717a", fontWeight: "700", letterSpacing: "0.05em" }}>STRATEGY</span>
                <span style={{ color: "#facc15", fontWeight: "700" }}>{group.strategy.name}</span>
                {group.strategy.phaseName &&
            <span style={{ color: "#71717a", fontSize: "12px" }}>· {group.strategy.phaseName}</span>
            }
                <span style={{ color: "#71717a", fontSize: "12px", marginLeft: "auto" }}>
                  {group.done}/{group.tasks.length} done
                </span>
              </div>
          }
            {!group.strategy && groups.length > 1 &&
          <div style={styles.strategyHeader}>
                <span style={{ fontSize: "10px", color: "#52525b", fontWeight: "700", letterSpacing: "0.05em" }}>NO STRATEGY</span>
              </div>
          }
            {safeMap(group.tasks, renderTask)}
          </section>)
        }

        {!loading && !error && tasks.length === 0 &&
        <p style={{ color: "#666", textAlign: "center" }}>No active directives.</p>
        }
      </div>
      <Toast toast={toast} onDismiss={clearToast} />
    </div>);

  function renderTask(task) {
    return (
        <div key={task.task_name} style={styles.taskCard(task.status)}>
            <div>
              <div style={styles.taskName}>{task.task_name}</div>
              <div style={styles.taskMeta}>
                Status: <span style={{ color: getStatusColor(task.status) }}>{task.status.toUpperCase()}</span>
                {describeHours(task.estimated_hours) && ` • Est: ${describeHours(task.estimated_hours)}`}
                {task.time_spent > 0 && ` • Time: ${(task.time_spent / 60).toFixed(1)}m`}
                {task.masterplan_id ? ` • Plan ${task.masterplan_id}` : ""}
              </div>
            </div>
            
            <div style={styles.actions}>
              {task.status !== "completed" &&
            <>
                  {task.status !== "in_progress" &&
              <button onClick={() => handleStart(task.task_name)} style={styles.actionBtn}>
                      ▶ Start
                    </button>
              }
                  {/* Opens the judgement step; it no longer completes anything itself, so
                      it keeps its label while in flight. The progress state belongs to
                      "Complete task" below — two buttons both reading "… Completing" was
                      ambiguous to a screen reader and to the tests. */}
                  <button
                    onClick={() => openJudgement(task.task_name)}
                    disabled={completing.has(task.task_name)}
                    style={{
                      ...styles.completeBtn,
                      ...(completing.has(task.task_name)
                        ? { opacity: 0.6, cursor: "progress" }
                        : null),
                    }}
                  >
                    ✅ Done
                  </button>
                </>
            }
              {task.masterplan_id && task.status !== "completed" && task.task_id &&
                <button
                  onClick={() => handlePromote(task)}
                  disabled={promoting.has(task.task_name)}
                  aria-label={`Make ${task.task_name} a strategy`}
                  title="This is how a phase gets done, not something done in a sitting. Make it a strategy and put the hours-sized tasks under it."
                  style={styles.actionBtn}>
                  {promoting.has(task.task_name) ? "…" : "↑ Strategy"}
                </button>
              }
              {/* Outside the not-completed guard on purpose: a task completed by mistake
                  is exactly the one you want to remove, so Delete stays available for
                  every status. */}
              <button
                onClick={() => handleDelete(task.task_name)}
                disabled={deleting.has(task.task_name)}
                aria-busy={deleting.has(task.task_name)}
                aria-label={`Delete ${task.task_name}`}
                title="Delete this task — cannot be undone"
                style={{
                  ...styles.deleteBtn,
                  ...(deleting.has(task.task_name)
                    ? { opacity: 0.6, cursor: "progress" }
                    : null),
                }}
              >
                {deleting.has(task.task_name) ? "… Deleting" : "🗑 Delete"}
              </button>
            </div>
            {/* Two questions, 1-5, asked once — at completion, where the answer is an
                observation rather than a guess. Nothing is pre-selected and Complete stays
                disabled until both are chosen, so a fabricated middle value cannot be
                recorded by clicking through. Cancel leaves the task untouched. */}
            {judging === task.task_name && (
              <div style={styles.judgementPanel}>
                <p style={styles.judgementIntro}>
                  How did that turn out? Both feed the plan&apos;s work-complexity measure.
                </p>
                {safeMap(
                  [
                    { key: "complexity", label: "Complexity", hint: "how many moving parts" },
                    { key: "difficulty", label: "Difficulty", hint: "how hard it actually was" },
                  ],
                  ({ key, label, hint }) => (
                    <div key={key} style={styles.judgementRow}>
                      <span style={styles.judgementLabel}>
                        {label} <span style={styles.judgementHint}>{hint}</span>
                      </span>
                      <span>
                        {safeMap([1, 2, 3, 4, 5], (n) => (
                          <button
                            key={n}
                            type="button"
                            aria-pressed={judgement[key] === n}
                            aria-label={`${label} ${n} of 5`}
                            onClick={() => setJudgement((prev) => ({ ...prev, [key]: n }))}
                            style={{
                              ...styles.scaleBtn,
                              ...(judgement[key] === n ? styles.scaleBtnActive : null),
                            }}
                          >
                            {n}
                          </button>
                        ))}
                      </span>
                    </div>
                  ),
                )}
                <div style={styles.judgementActions}>
                  <button
                    type="button"
                    onClick={() => handleComplete(task.task_name, judgement)}
                    disabled={
                      !judgement.complexity ||
                      !judgement.difficulty ||
                      completing.has(task.task_name)
                    }
                    aria-busy={completing.has(task.task_name)}
                    style={{
                      ...styles.completeBtn,
                      ...(!judgement.complexity || !judgement.difficulty
                        ? { opacity: 0.5, cursor: "not-allowed" }
                        : null),
                    }}
                  >
                    {completing.has(task.task_name) ? "… Completing" : "Complete task"}
                  </button>
                  <button type="button" onClick={cancelJudgement} style={styles.actionBtn}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>);
  }
}

// --- HELPERS & STYLES ---
const getStatusColor = (s) => {
  if (s === "completed") return "#00ffaa";
  if (s === "in_progress") return "#6cf";
  return "#888";
};

const styles = {
  container: { maxWidth: "700px", margin: "0 auto", padding: "2rem", color: "#eaeaea" },
  title: { borderLeft: "4px solid #f6f", paddingLeft: "12px", marginBottom: "24px" },
  successBanner: {
    background: "rgba(0, 255, 170, 0.1)", border: "1px solid #00ffaa", color: "#00ffaa",
    padding: "12px", borderRadius: "6px", marginBottom: "20px", fontWeight: "bold"
  },
  form: { display: "flex", flexDirection: "column", gap: "12px", marginBottom: "32px" },
  formRow: { display: "flex", gap: "12px", alignItems: "flex-end", flexWrap: "wrap" },
  fieldLabel: { display: "flex", flexDirection: "column", gap: "4px", fontSize: "12px", color: "#888" },
  smallInput: { width: "90px", padding: "10px", background: "#111", border: "1px solid #333", color: "#fff", borderRadius: "6px" },
  select: { padding: "10px", background: "#111", border: "1px solid #333", color: "#fff", borderRadius: "6px", minWidth: "160px" },
  formHint: { fontSize: "11px", color: "#666", margin: 0 },
  input: { flex: 1, padding: "12px", background: "#111", border: "1px solid #333", color: "#fff", borderRadius: "6px" },
  addButton: { background: "#f6f", color: "#000", border: "none", padding: "0 24px", fontWeight: "bold", borderRadius: "6px", cursor: "pointer" },
  list: { display: "flex", flexDirection: "column", gap: "12px" },
  strategyGroup: { borderLeft: "2px solid #facc1540", paddingLeft: "10px" },
  strategyHeader: { display: "flex", alignItems: "baseline", gap: "8px", padding: "4px 0 8px" },
  taskCard: (status) => ({
    display: "flex", justifyContent: "space-between", alignItems: "center",
    background: "#1a1a1a", border: "1px solid #333", padding: "16px", borderRadius: "8px",
    opacity: status === "completed" ? 0.5 : 1
  }),
  taskName: { fontSize: "16px", fontWeight: "500", marginBottom: "4px" },
  taskMeta: { fontSize: "12px", color: "#666" },
  actions: { display: "flex", gap: "8px" },
  actionBtn: { background: "#222", border: "1px solid #444", color: "#ccc", padding: "6px 12px", borderRadius: "4px", cursor: "pointer" },
  completeBtn: { background: "rgba(0, 255, 170, 0.2)", border: "1px solid #00ffaa", color: "#00ffaa", padding: "6px 12px", borderRadius: "4px", cursor: "pointer" },
  // Muted rather than alarming: destructive, but it is confirmed before it fires, and a
  // red button next to every task reads as a warning about the task rather than an action.
  deleteBtn: { background: "transparent", border: "1px solid #663333", color: "#cc7777", padding: "6px 12px", borderRadius: "4px", cursor: "pointer" },
  judgementPanel: { marginTop: 10, padding: 12, background: "#0d0d0d", border: "1px solid #262626", borderRadius: 6 },
  judgementIntro: { fontSize: 12, color: "#9a9a9a", marginBottom: 10 },
  judgementRow: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 8 },
  judgementLabel: { fontSize: 12, color: "#ccc" },
  judgementHint: { fontSize: 11, color: "#6b6b6b", marginLeft: 6 },
  scaleBtn: { background: "#1a1a1a", border: "1px solid #333", color: "#aaa", width: 30, height: 28, marginLeft: 4, borderRadius: 4, cursor: "pointer" },
  scaleBtnActive: { background: "rgba(0, 255, 170, 0.15)", borderColor: "#00ffaa", color: "#00ffaa" },
  judgementActions: { display: "flex", gap: 8, marginTop: 10 }
};
