import React, { useEffect, useMemo, useState } from "react";
import { getTasks, createTask, completeTask, startTask } from "../../api/tasks.js";
import { listMasterPlans } from "../../api/masterplan.js";
import { Toast } from "../shared/Toast";
import DomainError from "../shared/DomainError.jsx";
import { safeMap } from "../../utils/safe";
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
  // Task.masterplan_id drives ETA/WCU recalculation and the completion cascade. It was
  // reachable by the API and by agent tools but never set from this screen, so every
  // task created in the UI was permanently orphaned from every plan (walk-log item 17).
  const [masterplanId, setMasterplanId] = useState("");
  const [plans, setPlans] = useState([]);
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
  const { toast, showToast, clearToast } = useToast();
  const { publishProjection } = useMasterplanProjection();
  const { loading, error, data, execute: fetchTasks } = useApiCall(getTasks, {
    domain: "tasks",
  });

  const tasks = useMemo(() => {
    const items = Array.isArray(data) ? [...data] : [];
    return items.sort((a) => (a.status === "completed" ? 1 : -1));
  }, [data]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  // The plan picker is additive: if plans can't be listed (or none exist — creation is
  // Genesis-only today) the selector simply doesn't render and task creation is unaffected.
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
    const hours = Number.parseFloat(estimatedHours);
    if (!Number.isFinite(hours) || hours <= 0) {
      showToast("Estimated hours is required — a task without one is invisible to scoring.");
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

  const handleComplete = async (taskName) => {
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
      const res = await completeTask(taskName);

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
            Est. hours *
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
        </div>

        <p style={styles.formHint}>
          Estimated hours feeds the MasterPlan ETA and the Infinity Volume axis; leaving it
          empty records the task as zero effort.
        </p>
      </form>

      {/* --- TASK LIST --- */}
      <div style={styles.list}>
        <DomainError domain="tasks" error={error} onRetry={fetchTasks} />
        {loading ? <p>Syncing...</p> : safeMap(tasks, (task) =>
        <div key={task.task_name} style={styles.taskCard(task.status)}>
            <div>
              <div style={styles.taskName}>{task.task_name}</div>
              <div style={styles.taskMeta}>
                Status: <span style={{ color: getStatusColor(task.status) }}>{task.status.toUpperCase()}</span>
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
                  <button
                    onClick={() => handleComplete(task.task_name)}
                    disabled={completing.has(task.task_name)}
                    aria-busy={completing.has(task.task_name)}
                    style={{
                      ...styles.completeBtn,
                      ...(completing.has(task.task_name)
                        ? { opacity: 0.6, cursor: "progress" }
                        : null),
                    }}
                  >
                    {completing.has(task.task_name) ? "… Completing" : "✅ Done"}
                  </button>
                </>
            }
            </div>
          </div>)
        }
        
        {!loading && !error && tasks.length === 0 &&
        <p style={{ color: "#666", textAlign: "center" }}>No active directives.</p>
        }
      </div>
      <Toast toast={toast} onDismiss={clearToast} />
    </div>);

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
  taskCard: (status) => ({
    display: "flex", justifyContent: "space-between", alignItems: "center",
    background: "#1a1a1a", border: "1px solid #333", padding: "16px", borderRadius: "8px",
    opacity: status === "completed" ? 0.5 : 1
  }),
  taskName: { fontSize: "16px", fontWeight: "500", marginBottom: "4px" },
  taskMeta: { fontSize: "12px", color: "#666" },
  actions: { display: "flex", gap: "8px" },
  actionBtn: { background: "#222", border: "1px solid #444", color: "#ccc", padding: "6px 12px", borderRadius: "4px", cursor: "pointer" },
  completeBtn: { background: "rgba(0, 255, 170, 0.2)", border: "1px solid #00ffaa", color: "#00ffaa", padding: "6px 12px", borderRadius: "4px", cursor: "pointer" }
};
