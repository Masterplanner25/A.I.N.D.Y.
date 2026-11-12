import { useEffect, useState } from "react";
import { listActiveGoals } from "../../api/goals.js";
import { safeMap } from "../../utils/safe";
import { startingPoints } from "../../utils/agentStartingPoints";

// What to ask the agent (owner, 2026-11-11). The agent plans how to do a job, but nothing tells it which job is worth
// doing, so an empty box gets nothing done. These are jobs its tools do well, and the first one is about your top goal.
// Each fills the box; you edit the [brackets] and run it.

function goalsFrom(response) {
  const body = response?.data ?? response;
  if (Array.isArray(body)) return body;
  if (Array.isArray(body?.goals_list_result)) return body.goals_list_result;
  return [];
}

export default function AgentStartingPoints({ onPick }) {
  const [topGoal, setTopGoal] = useState(null);

  useEffect(() => {
    let live = true;
    listActiveGoals().then(
      (response) => {
        const top = goalsFrom(response)[0];
        if (live && top?.name) setTopGoal(top.name);
      },
      () => {}, // no goals to name: the first starting point says "what my plan says matters most" instead
    );
    return () => {
      live = false;
    };
  }, []);

  return (
    <section className="mt-8 space-y-3" data-testid="agent-starting-points">
      <div>
        <p className="text-[10px] uppercase tracking-wider text-zinc-600">What to ask</p>
        <p className="mt-1 text-xs text-zinc-500">
          Give the agent a job that takes several steps, ends in something that stays (a task, a memory, a draft, a
          market finding), and that you'd otherwise do by hand. A one-click change is quicker on its own screen.
        </p>
      </div>
      <ul className="space-y-2">
        {safeMap(startingPoints(topGoal), (point) => (
          <li key={point.title}>
            <button
              type="button"
              onClick={() => onPick(point.objective)}
              className="block w-full text-left border border-zinc-800/60 hover:border-zinc-700 rounded-lg px-3 py-2 transition-colors"
            >
              <span className="block text-xs text-zinc-200">{point.title}</span>
              <span className="block text-[11px] text-zinc-500">{point.why}</span>
              <span className="block text-[10px] font-mono text-zinc-600 mt-0.5">{point.uses}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-zinc-600">
        It sees your goals and plan but can't change your goals, can't open a specific web page, and reads code one file
        at a time. Plan changes through Genesis are high risk: leave them out until you trust the rest.
      </p>
    </section>
  );
}
