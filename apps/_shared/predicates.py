"""Named flow predicates shared by more than one app — runtime `register_predicate` (2.17.0, #680).

A conditional edge used to be `{"target": …, "condition": <lambda>}`. A lambda has no identity,
so the flow's graph signature could not include the decision — a predicate rewritten or rerouted
between suspend and resume would resume a parked run into a decision it was never planned for
(the runtime's `FLOW-GRAPH-SIGNATURE-1`). `{"target": …, "when": "<name>"}` names the decision;
the name enters the signature, and an unregistered name fails at resolution rather than falling
through.

The `watcher_evaluate_trigger` flow is declared twice, byte-identically, in
`apps/automation/flows/watcher_flows.py` and `apps/tasks/flows/tasks_flows.py`, each guarded by
`if "watcher_evaluate_trigger" not in FLOW_REGISTRY`. Its switch lives here once so both files
name the same predicates; the runtime refuses a name bound to a second, different callable, and
treats a re-import of the same function as a no-op. The fall-through edge is the runtime's own
`DEFAULT_PREDICATE` ("default"), not a predicate of ours.

Rules a predicate here must keep: a pure function of `state`, no I/O, no context — it is an
edge decision, and it runs on resume with only the persisted state to read.
"""

from __future__ import annotations

from AINDY.runtime.flow_engine import register_predicate

#: The three-way switch on `watcher_decision` after `watcher_record_decision_node`.
WATCHER_EXECUTE = "watcher_execute"
WATCHER_DEFER = "watcher_defer"


@register_predicate(WATCHER_EXECUTE)
def watcher_execute(state: dict) -> bool:
    return state.get("watcher_decision") == "execute"


@register_predicate(WATCHER_DEFER)
def watcher_defer(state: dict) -> bool:
    return state.get("watcher_decision") == "defer"
