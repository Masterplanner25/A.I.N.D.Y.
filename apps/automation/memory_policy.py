"""Automation-owned memory policies.

**Two keys, deliberately.** ``validate_memory_policy`` *requires* ``significance``,
but ``MemoryCaptureEngine`` reads ``default_significance`` when scoring
(``capture_rule.get("default_significance", 0.4)``) and never looks at ``significance``.
So a policy that declares only ``significance`` passes validation and then has no effect
on the score — which is why every domain's declared significance has been inert. Both
keys carry the same value until the runtime reconciles them; filed as MEM-POLICY-KEY-1
in RUNTIME_FEATURE_REQUESTS.md.

``min_significance`` is the gate: the engine drops a capture whose scored significance
falls below it (unless the caller passes ``force=True``, as runtime system-event capture
does).
"""


POLICIES = {
    "error_encountered": {
        "significance": 0.8,
        "default_significance": 0.8,
        "node_type": "insight",
        "memory_type": "failure",
        "tags": ["error", "learning"],
    },
    "insight_detected": {
        "significance": 0.7,
        "default_significance": 0.7,
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
    "flow_completion": {
        "significance": 0.5,
        "default_significance": 0.5,
        "min_significance": 0.6,
        "node_type": "outcome",
    },
}


def register(register_policy):
    for event_type, policy in POLICIES.items():
        register_policy(event_type, policy)
