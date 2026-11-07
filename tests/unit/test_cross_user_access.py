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
