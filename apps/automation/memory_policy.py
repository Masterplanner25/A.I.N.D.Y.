"""Automation-owned memory policies.

``significance`` is the declared base score. Under aindy-runtime >= 2.0.0 the capture
engine reads it directly (``significance`` → ``base_score`` → ``default_significance``,
first match wins), so declaring it once is enough. Earlier runtimes read only
``default_significance``, which made every domain's declared significance inert; the
duplicate key that worked around that (MEM-POLICY-KEY-1) is no longer needed.

Significance also now **floors** the read-side ``impact_score``, so a domain that says a
memory matters can actually cause it to be recalled. It is a floor, not a sum — a
well-connected node still outranks a merely well-declared one.

``min_significance`` is the gate: the engine drops a capture whose scored significance
falls below it. From 2.0.0 an *explicitly declared* ``min_significance`` is honoured even
for ``force=True`` captures, which is what makes the suppression below effective against
runtime system-event capture. A missing key still means force wins.
"""


POLICIES = {
    "error_encountered": {
        "significance": 0.8,
        "node_type": "insight",
        "memory_type": "failure",
        "tags": ["error", "learning"],
    },
    "insight_detected": {
        "significance": 0.7,
        "node_type": "insight",
    },
    # Suppressed. Every flow completion — including read-only list views like
    # `flow_runs_list` and `dashboard_overview` — is captured under this one event type,
    # because no app registers a per-workflow completion event. The content is a node
    # timing summary ("Flow 'x' completed: x_node(12ms). 1/1 nodes succeeded"), which is
    # execution telemetry, not domain meaning: it duplicates what domains already capture
    # deliberately (tasks captures `task_completed`, masterplan captures its own lock and
    # goal events) while adding a memory node every time someone opens an admin screen.
    #
    # Flow completions score ~0.29-0.45 under the engine's formula, so 0.6 gates all of
    # them. Raising the bar rather than deleting the policy keeps node_type/tags intact
    # if a future per-workflow event type wants to opt back in.
    #
    # This had NO effect before 2.0.0: runtime system-event capture passes force=True,
    # which skipped the gate entirely. That is why suppressing it left recall results
    # byte-identical when we first tried. 2.0.0 honours an explicit min_significance for
    # forced captures, so from this upgrade forward the suppression actually bites.
    "flow_completion": {
        "significance": 0.5,
        "min_significance": 0.6,
        "node_type": "outcome",
    },
}


def register(register_policy):
    for event_type, policy in POLICIES.items():
        register_policy(event_type, policy)
