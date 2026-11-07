"""One user's RippleTrace, Freelance and Social data stays theirs.

Another user's row reads as not found, and a summary covers only the caller's rows. What is computed over
every user's writing (RippleTrace's learning thresholds, strategies and playbooks) needs an operator.
"""

from __future__ import annotations

import uuid

import pytest

from apps.freelance.models.freelance import FreelanceOrder
from apps.freelance.schemas.freelance import FeedbackCreate
from apps.freelance.services import freelance_service
from apps.rippletrace.models import DropPointDB, PingDB
from apps.rippletrace.services import causal_engine, delta_engine, influence_graph, rippletrace_services
from apps.social.routes import social_router

pytestmark = pytest.mark.app_profile

OPERATOR_ONLY = [
    ("GET", "/apps/rippletrace/learning/stats"),
    ("POST", "/apps/rippletrace/learning/adjust"),
    ("GET", "/apps/rippletrace/playbooks"),
    ("GET", "/apps/rippletrace/playbooks/match/any"),
    ("GET", "/apps/rippletrace/playbooks/any"),
    ("GET", "/apps/rippletrace/strategies"),
    ("GET", "/apps/rippletrace/strategies/build"),
    ("GET", "/apps/rippletrace/strategies/match/any"),
    ("GET", "/apps/rippletrace/strategies/any"),
]
OWN_DROP_ONLY = [
    ("GET", "/apps/rippletrace/causal/chain/{id}"),
    ("GET", "/apps/rippletrace/narrative/{id}"),
    ("GET", "/apps/rippletrace/predictions/{id}"),
    ("GET", "/apps/rippletrace/recommendations/{id}"),
    ("POST", "/apps/rippletrace/learning/evaluate/{id}"),
]


def _drop(db, owner, ident=None):
    drop = DropPointDB(
        id=ident or f"drop-{uuid.uuid4().hex[:8]}",
        title="A piece",
        platform="notes.example.com",
        core_themes="shared",
        tagged_entities="shared",
        intent="published",
        user_id=owner,
    )
    db.add(drop)
    db.commit()
    return drop


def _order(db, owner):
    order = FreelanceOrder(
        client_name="Client",
        client_email="client@example.com",
        service_type="web",
        price=100.0,
        status="delivered",
        user_id=owner,
    )
    db.add(order)
    db.commit()
    return order


def _as_user(app, user_id=None, is_admin=False):
    from AINDY.services.auth_service import get_current_user

    user_id = user_id or uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(user_id), "is_admin": is_admin}
    return user_id


# ── RippleTrace ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method, path", OPERATOR_ONLY)
def test_what_spans_every_user_needs_an_operator(app, client, method, path):
    _as_user(app)
    refused = client.request(method, path)
    assert refused.status_code == 403, refused.text[:300]


@pytest.mark.parametrize("method, path", OWN_DROP_ONLY)
def test_another_users_drop_point_reads_as_not_found(app, client, db_session, method, path):
    drop = _drop(db_session, uuid.uuid4())
    _as_user(app)
    refused = client.request(method, path.format(id=drop.id))
    assert refused.status_code == 404, refused.text[:300]


def test_an_event_of_another_user_reads_as_not_found(app, client):
    _as_user(app)
    for direction in ("upstream", "downstream"):
        refused = client.get(f"/apps/rippletrace/event/{uuid.uuid4()}/{direction}")
        assert refused.status_code == 404, refused.text[:300]


def test_the_graphs_hold_only_the_callers_drop_points(db_session):
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    own = _drop(db_session, mine)
    _drop(db_session, theirs)

    influence = influence_graph.build_influence_graph(db_session, str(mine))
    assert [node["id"] for node in influence["nodes"]] == [own.id]
    assert influence["edges"] == []

    causal = causal_engine.build_causal_graph(db_session, str(mine))
    assert [node["id"] for node in causal["nodes"]] == [own.id]
    assert causal["causal_edges"] == []


def test_summaries_read_only_the_callers_history(db_session, monkeypatch):
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    own, other = _drop(db_session, mine), _drop(db_session, theirs)

    import apps.analytics.public as analytics

    monkeypatch.setattr(analytics, "list_score_snapshot_drop_point_ids", lambda db, min_count: [other.id, own.id])
    assert delta_engine.drop_point_ids_with_history(db_session, str(mine)) == [own.id]


def test_a_ping_needs_the_drop_points_owner(db_session):
    from types import SimpleNamespace

    from fastapi import HTTPException

    drop = _drop(db_session, uuid.uuid4())
    ping = SimpleNamespace(
        id="ping-1", drop_point_id=drop.id, ping_type="mention", source_platform="x", strength=1.0,
        date_detected=None, connection_summary=None, external_url=None, reaction_notes=None,
    )
    with pytest.raises(HTTPException) as refused:
        rippletrace_services.add_ping(db_session, ping, user_id=str(uuid.uuid4()))
    assert refused.value.status_code == 404
    assert db_session.query(PingDB).filter(PingDB.id == "ping-1").first() is None


def test_a_ripple_event_cannot_land_on_another_users_drop_point(db_session):
    drop = _drop(db_session, uuid.uuid4())
    with pytest.raises(ValueError, match="not found"):
        rippletrace_services.log_ripple_event(db_session, {"drop_point_id": drop.id}, user_id=str(uuid.uuid4()))


def test_a_caller_cannot_choose_a_drop_point_or_ping_id(db_session):
    """Ingest ids are sha256(user|url): a chosen id could take someone's future drop point first."""
    from types import SimpleNamespace

    from apps.rippletrace.services.content_ingest import drop_point_id_for

    owner, victim = uuid.uuid4(), uuid.uuid4()
    claimed = drop_point_id_for(str(victim), "https://victim.example/post")
    dp = SimpleNamespace(
        id=claimed, title="t", platform="p", url=None, date_dropped=None,
        core_themes=["a"], tagged_entities=["b"], intent="published",
    )
    made = rippletrace_services.add_drop_point(db_session, dp, user_id=str(owner))
    assert made.id != claimed and made.id.startswith("dp-manual-")
    assert db_session.query(DropPointDB).filter(DropPointDB.id == claimed).first() is None

    ping = SimpleNamespace(
        id="ping-chosen", drop_point_id=made.id, ping_type="mention", source_platform="x", strength=1.0,
        date_detected=None, connection_summary=None, external_url=None, reaction_notes=None,
    )
    stored = rippletrace_services.add_ping(db_session, ping, user_id=str(owner))
    assert stored.id != "ping-chosen" and stored.id.startswith("ping-manual-")


def _attempt(db, write, monkeypatch=None):
    """Run a write that may collide on a primary key, rolling back only that write.

    The session sits in the fixture's outer transaction, so a plain rollback would also erase
    the rows this test set up. A savepoint holds the attempt; a commit inside it only flushes.
    """
    if monkeypatch is not None:
        monkeypatch.setattr(db, "commit", db.flush)
    try:
        with db.begin_nested():
            write()
            db.flush()
    except Exception:
        pass  # the id is taken: the write fails, which is the safe outcome
    if monkeypatch is not None:
        monkeypatch.undo()


def test_ingest_never_updates_a_drop_point_another_user_holds(db_session):
    """A row with the caller's deterministic id that someone else owns is left untouched."""
    from apps.rippletrace.services.content_ingest import drop_point_id_for, upsert_drop_point

    victim, squatter = uuid.uuid4(), uuid.uuid4()
    url = "https://victim.example/post"
    _drop(db_session, squatter, ident=drop_point_id_for(str(victim), url))

    _attempt(db_session, lambda: upsert_drop_point(db_session, user_id=str(victim), url=url, title="Victim's piece"))
    row = db_session.query(DropPointDB).filter(DropPointDB.id == drop_point_id_for(str(victim), url)).one()
    assert row.user_id == squatter and row.title == "A piece"


def test_a_citation_never_lands_on_another_drop_points_ping(db_session, monkeypatch):
    from apps.rippletrace.services import citation_record
    from apps.rippletrace.services.ripple_detection import ping_id_for

    victim, squatter = uuid.uuid4(), uuid.uuid4()
    victims_drop, squatters_drop = _drop(db_session, victim), _drop(db_session, squatter)
    url = "https://cites.example/page"
    squatted = PingDB(
        id=ping_id_for(victims_drop.id, url), drop_point_id=squatters_drop.id, ping_type="mention",
        source_platform="x", user_id=squatter,
    )
    db_session.add(squatted)
    db_session.commit()
    monkeypatch.setattr(
        citation_record, "_check", lambda *a, **k: (citation_record.VERIFIED, "seen", "Page")
    )

    _attempt(
        db_session,
        lambda: citation_record.record_citation(db_session, drop_point=victims_drop, url=url, user_id=str(victim)),
        monkeypatch=monkeypatch,
    )
    db_session.refresh(squatted)
    assert squatted.drop_point_id == squatters_drop.id
    assert squatted.verification != citation_record.VERIFIED


def test_the_legacy_shared_key_surface_is_gone(app, client):
    from AINDY.config import settings

    headers = {"X-API-Key": settings.AINDY_API_KEY or "test"}
    for path in ("/apps/influence_graph", "/apps/dashboard", "/apps/narrative/x", "/apps/learning_stats"):
        assert client.get(path, headers=headers).status_code == 404, path


# ── Network bridge ──────────────────────────────────────────────────────────────────────────


def test_the_shared_key_lists_only_the_gateways_authors(db_session):
    from apps.authorship.models import AuthorDB
    from apps.network_bridge.services import network_bridge_services as bridge

    db_session.add_all([
        AuthorDB(id=f"a-{uuid.uuid4().hex}", name="person@example.com", platform=bridge.SIGN_IN_PLATFORM),
        AuthorDB(id=f"a-{uuid.uuid4().hex}", name="owned", platform="Gateway", user_id=uuid.uuid4()),
        AuthorDB(id=f"a-{uuid.uuid4().hex}", name="gateway-author", platform="Gateway"),
    ])
    db_session.commit()

    names = {row["name"] for row in bridge.list_authors(db_session, limit=10_000)}
    assert "gateway-author" in names
    assert "person@example.com" not in names and "owned" not in names


def test_a_sign_in_author_row_has_its_owner(db_session, monkeypatch):
    from apps.network_bridge.services import network_bridge_services as bridge

    seen = {}
    monkeypatch.setattr(bridge, "register_author", lambda **kw: seen.update(kw) or {"id": "a"})
    monkeypatch.setattr(bridge, "dispatch_syscall", lambda *a, **k: {})
    user = str(uuid.uuid4())
    try:
        bridge.connect_external_author(
            db_session, author_name="me@example.com", platform=bridge.SIGN_IN_PLATFORM,
            connection_type="sign_in", notes=None, user_id=user,
        )
    except Exception:
        pass  # later steps are not under test; the author row is written first
    assert seen.get("user_id") == user


# ── Freelance ───────────────────────────────────────────────────────────────────────────────


def test_only_the_orders_owner_can_rate_it(db_session):
    owner = uuid.uuid4()
    order = _order(db_session, owner)
    rating = FeedbackCreate(order_id=order.id, rating=1, feedback_text="poor")

    with pytest.raises(ValueError, match="not found"):
        freelance_service.collect_feedback(db_session, rating, user_id=str(uuid.uuid4()))
    db_session.refresh(order)
    assert order.delivery_quality_score is None

    assert freelance_service.collect_feedback(db_session, rating, user_id=str(owner)).user_id == owner


def test_revenue_metrics_belong_to_one_user(db_session):
    owner, other = uuid.uuid4(), uuid.uuid4()
    _order(db_session, owner)

    written = freelance_service.update_revenue_metrics(db_session, user_id=str(owner))
    assert written.user_id == owner and written.total_revenue == 100.0

    assert freelance_service.get_latest_metrics(db_session, str(owner)).id == written.id
    assert freelance_service.get_latest_metrics(db_session, str(other)) is None


def test_an_idempotency_key_is_the_callers_alone(db_session, monkeypatch):
    """Another user's Idempotency-Key makes a new order for the caller, never returns theirs."""
    from apps.freelance.schemas.freelance import FreelanceOrderCreate

    monkeypatch.setattr(freelance_service, "_finalize_created_order", lambda *a, **k: None)
    owner, other = uuid.uuid4(), uuid.uuid4()
    order = FreelanceOrderCreate(client_name="Owner's client", client_email="c@example.com", service_type="web")

    first, created = freelance_service.create_order(
        db_session, order, user_id=str(owner), idempotency_key="shared-key", return_created=True
    )
    assert created and first.user_id == owner

    theirs, created = freelance_service.create_order(
        db_session,
        FreelanceOrderCreate(client_name="Mine", client_email="m@example.com", service_type="web"),
        user_id=str(other),
        idempotency_key="shared-key",
        return_created=True,
    )
    assert created and theirs.id != first.id and theirs.user_id == other

    replay, created = freelance_service.create_order(
        db_session, order, user_id=str(owner), idempotency_key="shared-key", return_created=True
    )
    assert not created and replay.id == first.id


def test_a_scoped_idempotency_key_fits_its_column():
    from apps.freelance.services.idempotency import scoped_idempotency_key

    owner = str(uuid.uuid4())
    assert scoped_idempotency_key(owner, "k") == f"{owner}:k"
    assert scoped_idempotency_key(owner, "k") != scoped_idempotency_key(str(uuid.uuid4()), "k")
    assert scoped_idempotency_key(owner, None) is None
    long_key = scoped_idempotency_key(owner, "x" * 400)
    assert len(long_key) <= 255 and long_key.startswith(f"{owner}:sha256:")


# ── Social ──────────────────────────────────────────────────────────────────────────────────


class FakeCursor(list):
    def sort(self, *_args):
        return self

    def limit(self, _count):
        return self


class FakePosts:
    def __init__(self, *docs):
        self.docs = list(docs)
        self.queries = []
        self.inserted = []
        self.updates = []

    def find(self, query):
        self.queries.append(query)
        return FakeCursor()

    def find_one(self, query):
        return next((d for d in self.docs if d.get("id") == query.get("id")), None)

    def insert_one(self, doc):
        self.inserted.append(doc)

    def update_one(self, query, update):
        self.updates.append((query, update))


def _mongo(app, posts):
    from AINDY.db.mongo_setup import get_optional_mongo_db

    database = {"posts": posts, "comments": FakePosts(), "profiles": FakePosts()}
    app.dependency_overrides[get_optional_mongo_db] = lambda: database


@pytest.mark.parametrize(
    "doc, visible",
    [
        ({"user_id": "author", "trust_tier_required": "inner"}, False),
        ({"user_id": "author", "trust_tier_required": "collab"}, False),
        ({"user_id": "author", "visibility": "private"}, False),
        ({"user_id": "author", "trust_tier_required": "observer"}, True),
        ({"user_id": "author", "trust_tier_required": "system"}, True),
        ({"user_id": "author"}, True),
        ({"user_id": "viewer", "trust_tier_required": "inner"}, True),
        ({"user_id": "viewer", "visibility": "private"}, True),
    ],
)
def test_who_can_see_a_post(doc, visible):
    assert social_router._post_is_visible(doc, "viewer") is visible


def test_the_feed_asks_only_for_what_the_viewer_can_see(app, client):
    posts = FakePosts()
    _mongo(app, posts)
    viewer = _as_user(app)

    assert client.get("/apps/social/feed").status_code == 200
    assert posts.queries == [social_router._visible_posts_query(str(viewer))]

    # A filter narrows that; it cannot widen it.
    assert client.get("/apps/social/feed?trust_filter=inner").status_code == 200
    assert posts.queries[-1]["$or"] == social_router._visible_posts_query(str(viewer))["$or"]
    assert posts.queries[-1]["trust_tier_required"] == "inner"


def test_a_hidden_post_reads_as_not_found(app, client):
    posts = FakePosts({"id": "secret", "user_id": str(uuid.uuid4()), "trust_tier_required": "inner"})
    _mongo(app, posts)
    _as_user(app)

    assert client.get("/apps/social/posts/secret/comments").status_code == 404
    assert client.post("/apps/social/posts/secret/comments", json={"content": "hi"}).status_code == 404
    assert client.post("/apps/social/posts/secret/interact", json={"action": "like"}).status_code == 404
    assert posts.updates == []


def test_a_post_is_authored_by_the_caller_whatever_the_body_says(app, client):
    posts = FakePosts()
    _mongo(app, posts)
    caller = _as_user(app)

    client.post(
        "/apps/social/post",
        json={"author_id": str(uuid.uuid4()), "author_username": "someone", "content": "hello"},
    )
    assert [doc["author_id"] for doc in posts.inserted] == [str(caller)]


def test_a_posts_identity_time_name_and_counters_are_the_servers(app, client):
    posts = FakePosts()
    _mongo(app, posts)
    _as_user(app)

    client.post(
        "/apps/social/post",
        json={
            "id": "someone-elses-post",
            "author_id": "x",
            "author_username": "the_owner",
            "content": "hello",
            "created_at": "2099-01-01T00:00:00",
            "likes": 999999,
            "boosts": 5,
            "impressions": 7,
            "engagement_score": 99.0,
        },
    )
    [doc] = posts.inserted
    assert doc["id"] != "someone-elses-post"
    assert doc["created_at"].year < 2099
    assert doc["author_username"] == "anonymous"  # no canonical name, no profile: not the body's
    assert doc["likes"] == doc["boosts"] == doc["impressions"] == 0
    assert doc["engagement_score"] == 0.0


def test_one_interaction_counts_once_whatever_the_body_says(app, client, monkeypatch):
    posts = FakePosts({"id": "public", "user_id": str(uuid.uuid4())})
    _mongo(app, posts)
    _as_user(app)
    deltas = []
    monkeypatch.setattr(social_router, "record_metric_deltas", lambda **kw: deltas.append(kw["deltas"]))
    monkeypatch.setattr(social_router, "_maybe_capture_performance_signal", lambda *a, **k: (a[0], []), raising=False)

    client.post("/apps/social/posts/public/interact", json={"action": "like", "amount": 1_000_000_000})
    assert posts.updates == [({"id": "public"}, {"$inc": {"likes": 1}})]
    assert deltas == [{"likes": 1}]


def test_a_profile_cannot_set_its_own_metrics(app, client):
    from AINDY.db.mongo_setup import get_optional_mongo_db

    profiles = FakePosts()
    app.dependency_overrides[get_optional_mongo_db] = lambda: {
        "posts": FakePosts(), "comments": FakePosts(), "profiles": profiles
    }
    _as_user(app)

    client.post(
        "/apps/social/profile",
        json={"username": "newcomer", "metrics_snapshot": {"trust_score": 100.0, "twr_score": 9.9}},
    )
    [doc] = profiles.inserted
    assert doc["metrics_snapshot"]["trust_score"] == 50.0
    assert doc["metrics_snapshot"]["twr_score"] == 0.0
