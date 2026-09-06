from __future__ import annotations

from AINDY.db.dao.memory_node_dao import MemoryNodeDAO
from AINDY.db.models.user_identity import UserIdentity
from AINDY.core.execution_signal_helper import queue_system_event


def _ensure_user_score_via_syscall(*, db, user_id) -> dict:
    import uuid

    from AINDY.kernel.syscall_dispatcher import SyscallContext, get_dispatcher

    ctx = SyscallContext(
        execution_unit_id=str(uuid.uuid4()),
        user_id=str(user_id),
        capabilities=["analytics.write"],
        trace_id="",
        metadata={"_db": db},
    )
    result = get_dispatcher().dispatch(
        "sys.v1.analytics.init_user_score",
        {"user_id": str(user_id)},
        ctx,
    )
    if result["status"] != "success":
        raise RuntimeError(result.get("error", "analytics.init_user_score failed"))
    return dict(result.get("data") or {})


def initialize_signup_state(*, db, user) -> dict:
    from AINDY.kernel.syscall_dispatcher import dispatch_syscall

    identity = (
        db.query(UserIdentity)
        .filter(UserIdentity.user_id == user.id)
        .first()
    )
    if identity is None:
        identity = UserIdentity(
            user_id=user.id,
            preferred_languages=[],
            preferred_tools=[],
            avoided_tools=[],
            evolution_log=[],
        )
        db.add(identity)
        db.commit()
        db.refresh(identity)

    memory_dao = MemoryNodeDAO(db)
    initial_memory = memory_dao.save(
        content="User account created",
        source="auth.register",
        tags=["identity", "identity_init"],
        user_id=str(user.id),
        node_type="insight",
        extra={
            "type": "identity",
            "context": "identity_init",
        },
    )

    score = _ensure_user_score_via_syscall(db=db, user_id=user.id)

    agent_result = dispatch_syscall(
        "sys.v1.agent.ensure_initial_run",
        {"user_id": str(user.id)},
        db=db,
        user_id=str(user.id),
    )
    agent_run_id = None
    if agent_result.get("status") == "success":
        agent_run_id = agent_result.get("data", {}).get("run_id")

    # Provision the social profile here rather than leaving it to the user's first visit to
    # `/profile/:username`. Without this a freshly registered account 404s on
    # `GET /apps/social/profile/{username}` and that screen opens in create-mode every time.
    #
    # Tolerant on purpose, matching the agent-run step above rather than the score step:
    # social is Mongo-backed and degradable, and the prod compose ships without Mongo. A
    # registration must not fail because an optional datastore is absent, so a non-success
    # result is recorded and ignored.
    social_result = dispatch_syscall(
        "sys.v1.social.ensure_profile",
        {"user_id": str(user.id)},
        db=db,
        user_id=str(user.id),
    )
    social_profile = (
        social_result.get("data", {}) if social_result.get("status") == "success" else {}
    )

    queue_system_event(
        db=db,
        event_type="identity.created",
        user_id=user.id,
        payload={
            "email": user.email,
            "timestamp": user.created_at.isoformat() if user.created_at else None,
            "memory_node_id": initial_memory["id"],
            "agent_run_id": agent_run_id,
        },
        required=True,
    )

    return {
        "memory": initial_memory,
        "metrics": {
            "score": score.get("master_score", 0.0),
            "trajectory": "baseline",
        },
        "agent_context": {
            "status": "initialized",
            "steps": 0,
            "run_id": agent_run_id,
        },
        # `created` distinguishes a new profile from one that already existed; `degraded`
        # says Mongo was unreachable, which is a normal deployment state rather than a
        # failure. Both are reported so a caller can tell "no profile" from "no Mongo".
        "social_profile": {
            "created": bool(social_profile.get("created")),
            "degraded": bool(social_profile.get("degraded")),
            "username": social_profile.get("username"),
        },
    }

