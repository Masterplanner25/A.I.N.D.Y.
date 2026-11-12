import { useCallback, useEffect, useState } from "react";
import { confirmGoal, createGoal, dropGoal, getGoalsOverview, updateGoal } from "../../api/goals.js";
import { safeMap } from "../../utils/safe";

// What you are working toward, above any one plan (GOALS_LAYER_SPEC §6, decided 2026-11-09).
// Proposals come from your plan's anchor and success criteria and act on nothing until you confirm them. A goal is
// measured by your anchor, by the objectives it links to, or declared (no number; you mark it done). Never a score.

const BUTTON = "px-3 py-1.5 rounded-lg text-[11px] font-bold uppercase tracking-wider transition-colors disabled:opacity-40";
const PRIMARY = `${BUTTON} bg-[#00ffaa] text-black hover:bg-[#00ffaa]/80`;
const QUIET = `${BUTTON} border border-zinc-700 text-zinc-400 hover:bg-zinc-800`;
const SOURCE = { anchor: "your anchor", success_criterion: "a success criterion", stated: "you" };

function unwrap(response) {
  return response?.data && !response?.proposed ? response.data : response;
}

function errorText(err, fallback) {
  let raw = err?.data ?? err?.body;
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      raw = null;
    }
  }
  const detail = raw?.detail ?? raw;
  if (typeof detail === "string") return detail;
  return detail?.message || raw?.message || fallback;
}

function progressText(goal) {
  if (goal.measure === "declared") return "declared: you mark it done";
  if (goal.progress === null || goal.progress === undefined) {
    return goal.measure === "anchor" ? "no measurement yet" : "no work planned yet";
  }
  // An objectives goal at 100% has done all its planned work; it is still the person's to call done (owner, 2026-11-09).
  if (goal.measure === "objectives" && goal.progress >= 0.999) return "all planned work done";
  return `${Math.round(goal.progress * 100)}% attained`;
}

function targetText(goal) {
  if (!goal.target_value) return "";
  const target = `${Number(goal.target_value).toLocaleString()} ${goal.unit || ""}`.trim();
  const due = goal.target_date ? ` by ${goal.target_date.slice(0, 10)}` : "";
  return `${target}${due}`;
}

function measureText(goal) {
  if (goal.measure === "anchor") {
    const target = targetText(goal);
    return `anchor${target ? `: ${target}` : ""}`;
  }
  // Any other goal's target is shown only; it is never what measures the goal (owner, 2026-11-11).
  const target = targetText(goal) ? ` · target ${targetText(goal)}` : "";
  if (goal.measure === "objectives") {
    return `through ${safeMap(goal.objectives || [], (o) => o.name).join(", ") || "its objectives"}${target}`;
  }
  return `declared${target}`;
}

// Priority is 0.45 of a goal's rank, which the loop, the gate and agent ranking read (GOALS_LAYER_SPEC §3).
const PRIORITIES = [["low", 0.3], ["normal", 0.5], ["high", 0.7], ["top", 0.9]];

function nearestPriority(value) {
  const v = Number(value ?? 0.5);
  return PRIORITIES.reduce((best, p) => (Math.abs(p[1] - v) < Math.abs(best[1] - v) ? p : best))[1];
}

function PrioritySelect({ goal, busy, onPriority }) {
  return (
    <label className="flex items-center gap-1 text-[11px] text-zinc-500">
      priority
      <select aria-label={`Priority of ${goal.name}`} disabled={busy} value={nearestPriority(goal.priority)}
        onChange={(e) => onPriority(goal.id, Number(e.target.value))}
        className="rounded border border-zinc-800 bg-zinc-950 px-1 py-0.5 text-[11px] text-zinc-300">
        {safeMap(PRIORITIES, ([label, value]) => <option key={label} value={value}>{label}</option>)}
      </select>
    </label>
  );
}

function ObjectivePicker({ objectives, chosen, onChange, disabled }) {
  if (!objectives.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {safeMap(objectives, (o) => (
        <label key={o.id} className="flex items-center gap-1 text-[11px] text-zinc-400">
          <input
            type="checkbox"
            disabled={disabled}
            checked={chosen.includes(o.id)}
            onChange={(e) => onChange(e.target.checked ? [...chosen, o.id] : chosen.filter((id) => id !== o.id))}
          />
          {o.name}
        </label>
      ))}
    </div>
  );
}

function Proposal({ goal, objectives, busy, onConfirm, onDrop }) {
  const [chosen, setChosen] = useState(() => safeMap(goal.objectives || [], (o) => o.id));
  const anchor = goal.measure === "anchor";
  const how = anchor ? measureText(goal)
    : chosen.length ? "measured through the objectives ticked" : "declared: no number, you mark it done";
  return (
    <li className="space-y-2 border-t border-zinc-800/60 pt-3" data-testid="goal-proposal">
      <div>
        <p className="text-sm text-zinc-100">{goal.name}</p>
        <p className="text-[11px] text-zinc-500">from {SOURCE[goal.source] || goal.source} · {how}</p>
      </div>
      {!anchor && <ObjectivePicker objectives={objectives} chosen={chosen} onChange={setChosen} disabled={busy} />}
      <div className="flex gap-2">
        <button type="button" className={PRIMARY} disabled={busy}
          onClick={() => onConfirm(goal.id, anchor ? {} : { objective_ids: chosen })}>Confirm</button>
        <button type="button" className={QUIET} disabled={busy} onClick={() => onDrop(goal.id)}>Drop</button>
      </div>
    </li>
  );
}

function Goal({ goal, busy, onDone, onReopen, onDrop, onPriority }) {
  const progress = goal.progress;
  const done = goal.status === "completed";
  return (
    <li className="space-y-1 border-t border-zinc-800/60 pt-3" data-testid="goal">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className={`text-sm ${done ? "text-zinc-500 line-through" : "text-zinc-100"}`}>{goal.name}</p>
        <p className="text-[11px] text-zinc-400">{done ? "done" : progressText(goal)}</p>
      </div>
      <p className="text-[11px] text-zinc-500">{measureText(goal)} · from {SOURCE[goal.source] || "you"}</p>
      {progress !== null && progress !== undefined && !done &&
        <div className="h-1 rounded bg-zinc-800">
          <div className="h-1 rounded bg-[#00ffaa]" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
      }
      <div className="flex flex-wrap items-center gap-2 pt-1">
        {goal.status === "active" && <PrioritySelect goal={goal} busy={busy} onPriority={onPriority} />}
        {goal.status === "active" && goal.measure !== "anchor" &&
          <button type="button" className={QUIET} disabled={busy} onClick={() => onDone(goal.id)}>Mark done</button>}
        {done && <button type="button" className={QUIET} disabled={busy} onClick={() => onReopen(goal.id)}>Reopen</button>}
        <button type="button" className={QUIET} disabled={busy} onClick={() => onDrop(goal.id)}>Drop</button>
      </div>
    </li>
  );
}

const INPUT = "rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600";

function AddGoal({ objectives, busy, onAdd }) {
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState([]);
  const [targetValue, setTargetValue] = useState("");
  const [unit, setUnit] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const number = Number(targetValue);
  // The server needs a number for a unit or date; say so here rather than send a request it refuses.
  const targetIncomplete = !targetValue && Boolean(unit.trim() || targetDate);
  const targetInvalid = Boolean(targetValue) && !(number > 0);
  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim() || targetIncomplete || targetInvalid) return;
    const target = targetValue ? { targetValue: number, unit: unit.trim(), targetDate } : {};
    if (await onAdd({ name: name.trim(), objectiveIds: chosen, ...target })) {
      setName("");
      setChosen([]);
      setTargetValue("");
      setUnit("");
      setTargetDate("");
    }
  };
  return (
    <form className="space-y-2 border-t border-zinc-800/60 pt-3" onSubmit={submit}>
      <div className="flex gap-2">
        <input aria-label="New goal" placeholder="Add a goal of your own" value={name} onChange={(e) => setName(e.target.value)}
          className={`min-w-0 flex-1 ${INPUT}`} />
        <button type="submit" className={PRIMARY} disabled={busy || !name.trim() || targetIncomplete || targetInvalid}>Add</button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] text-zinc-500">target (optional, shown only)</span>
        <input aria-label="Target number" type="number" min="0" step="any" placeholder="50" value={targetValue}
          onChange={(e) => setTargetValue(e.target.value)} className={`w-20 ${INPUT}`} />
        <input aria-label="Target unit" placeholder="posts" maxLength={32} value={unit}
          onChange={(e) => setUnit(e.target.value)} className={`w-24 ${INPUT}`} />
        <input aria-label="Target date" type="date" value={targetDate}
          onChange={(e) => setTargetDate(e.target.value)} className={INPUT} />
      </div>
      {targetIncomplete && <p className="text-[11px] text-amber-400">A unit or date needs a target number.</p>}
      {targetInvalid && <p className="text-[11px] text-amber-400">The target number must be above 0.</p>}
      <ObjectivePicker objectives={objectives} chosen={chosen} onChange={setChosen} disabled={busy} />
    </form>
  );
}

export default function GoalsPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () => getGoalsOverview().then((r) => setData(unwrap(r)), (e) => setError(errorText(e, "Could not load your goals."))),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  const run = async (action) => {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
      return true;
    } catch (e) {
      setError(errorText(e, "That didn't work."));
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (!data && !error) return null;
  const objectives = data?.objectives || [];
  const proposed = data?.proposed || [];
  const goals = data?.goals || [];

  return (
    <section className="border border-zinc-800/60 rounded-lg p-4 space-y-3" data-testid="goals-panel">
      <div>
        <p className="text-[10px] uppercase tracking-wider text-zinc-600">Goals</p>
        <p className="text-xs text-zinc-400 mt-1">
          What you are working toward, above any one plan. A goal is measured by your anchor or by the objectives it
          links to, or it is declared and you mark it done.
        </p>
      </div>
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
      {proposed.length > 0 &&
        <div data-testid="goal-proposals">
          <p className="text-[10px] uppercase tracking-wider text-zinc-600">From your plan: confirm, adjust or drop</p>
          <ul className="space-y-3 mt-1">
            {safeMap(proposed, (g) => (
              <Proposal key={g.id} goal={g} objectives={objectives} busy={busy}
                onConfirm={(id, edits) => run(() => confirmGoal(id, edits))}
                onDrop={(id) => run(() => dropGoal(id))} />
            ))}
          </ul>
        </div>
      }
      <ul className="space-y-3">
        {goals.length === 0 && proposed.length === 0 && <li className="text-[11px] text-zinc-500">No goals yet.</li>}
        {safeMap(goals, (g) => (
          <Goal key={g.id} goal={g} busy={busy}
            onDone={(id) => run(() => updateGoal(id, { status: "completed" }))}
            onReopen={(id) => run(() => updateGoal(id, { status: "active" }))}
            onDrop={(id) => run(() => dropGoal(id))}
            onPriority={(id, priority) => run(() => updateGoal(id, { priority }))} />
        ))}
      </ul>
      <AddGoal objectives={objectives} busy={busy} onAdd={(goal) => run(() => createGoal(goal))} />
    </section>
  );
}
