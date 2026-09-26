import { useState } from "react";
import { safeMap } from "../../utils/safe";

// What an agent step returned, readable. Collaborator showed each step's status and never its
// result, so the research a run found was visible only in the database (2026-09-26). One renderer
// per tool whose result shape is known (sampled from live `agent_steps`); anything else falls
// back to collapsed JSON.

const Text = ({ children }) => (
  <p className="text-xs text-zinc-300 leading-relaxed whitespace-pre-wrap">{children}</p>
);

function Expandable({ text, limit = 600 }) {
  const [open, setOpen] = useState(false);
  const long = text.length > limit;
  return (
    <div>
      <Text>{open || !long ? text : `${text.slice(0, limit)}…`}</Text>
      {long && (
        <button
          onClick={() => setOpen((v) => !v)}
          className="mt-1 text-[10px] uppercase tracking-wider text-[#00ffaa] hover:underline"
        >
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </div>
  );
}

const isTelemetry = (node) => String(node?.source || "").startsWith("system_event:");

export default function StepResult({ tool, result }) {
  if (!result || typeof result !== "object") return null;

  switch (tool) {
    case "research.query":
      return result.raw_result ? <Expandable text={String(result.raw_result)} /> : null;

    case "memory.recall": {
      const nodes = Array.isArray(result.nodes) ? result.nodes : [];
      const notes = nodes.filter((n) => !isTelemetry(n));
      const hidden = nodes.length - notes.length;
      if (!nodes.length) return <Text>No notes found.</Text>;
      return (
        <div className="space-y-1">
          {safeMap(notes, (n, i) => (
            <Text key={n.id || i}>• {String(n.content || "").slice(0, 240)}</Text>
          ))}
          {hidden > 0 && (
            <p className="text-[10px] text-zinc-600">
              {hidden} system event{hidden === 1 ? "" : "s"} hidden
            </p>
          )}
        </div>
      );
    }

    case "search.query": {
      const hits = (Array.isArray(result.results) ? result.results : []).filter((h) => h?.title || h?.snippet);
      if (!hits.length) return <Text>No results.</Text>;
      return (
        <div className="space-y-1">
          {safeMap(hits, (h, i) => (
            <Text key={i}>
              • {h.title}
              {h.snippet ? ` — ${h.snippet}` : ""}
            </Text>
          ))}
        </div>
      );
    }

    case "task.create":
      return result.name ? (
        <Text>
          Created task{result.task_id ? ` #${result.task_id}` : ""}: {result.name}
        </Text>
      ) : null;

    case "memory.write":
      return result.node_id ? <Text>Saved a note.</Text> : null;

    case "reasoning.evaluate":
      return result.decision_type ? (
        <Text>
          Recommends {String(result.decision_type).replace(/_/g, " ")}
          {result.next_action_title ? ` — ${result.next_action_title}` : ""}
        </Text>
      ) : null;

    case "arm.analyze":
      return result.summary ? <Expandable text={String(result.summary)} /> : null;

    case "leadgen.act":
      return (
        <Text>
          {result.dry_run ? "Dry run: " : ""}
          {result.count ?? 0} action{result.count === 1 ? "" : "s"}
          {Array.isArray(result.skipped) && result.skipped.length
            ? `, ${result.skipped.length} skipped`
            : ""}
        </Text>
      );

    default:
      return (
        <details>
          <summary className="text-[10px] uppercase tracking-wider text-zinc-500 cursor-pointer">
            Result
          </summary>
          <pre className="mt-1 text-[10px] text-zinc-400 whitespace-pre-wrap break-all">
            {JSON.stringify(result, null, 2)}
          </pre>
        </details>
      );
  }
}
