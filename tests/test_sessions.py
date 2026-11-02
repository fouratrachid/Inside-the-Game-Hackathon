import json

import pytest
from conftest import synthetic_session
from fastapi.testclient import TestClient

from app.main import create_app
from app.sessions import RECENT_EVENTS, MatchSession, SessionStore
from app.synthetic import SyntheticSource


class ShortSyntheticSource(SyntheticSource):
    """The seeded fictional match cut to 150 events, so the replay ends mid-match quickly."""

    async def events(self, match_id):
        return (await super().events(match_id))[:150]


class RecordingChat:
    """Fake chat: records every internal ChatRequest instead of calling a model."""

    def __init__(self):
        self.requests = []

    async def ask(self, request):
        self.requests.append(request)
        return {"text": "ok", "evidence_event_ids": []}


def frames(body):
    parsed = []
    for block in body.split("\n\n"):
        lines = block.splitlines()
        kind = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if kind and data:
            parsed.append((kind, json.loads(data)))
    return parsed


@pytest.fixture
def app(monkeypatch):
    # These Phase 1 tests target the original pipeline; Phase 2 tests cover LangGraph.
    monkeypatch.setenv("GAME_AGENT", "maf")
    application = create_app()
    application.state.source = ShortSyntheticSource()
    application.state.chat = RecordingChat()
    return application


def stream(client):
    response = client.get("/matches/1/stream", params={"speed": 1000})
    assert response.status_code == 200
    return frames(response.text)


def test_stream_announces_a_session_and_chat_matches_last_update(app):
    with TestClient(app) as client:
        replayed = stream(client)
        kind, match = replayed[0]
        assert kind == "match" and app.state.sessions.get(match["session_id"])
        response = client.post(
            "/chat", json={"question": "Score?", "session_id": match["session_id"]}
        )
    assert response.status_code == 200
    updates = [data for kind, data in replayed if kind == "update"]
    last = updates[-1]
    snapshot = app.state.chat.requests[0].snapshot
    assert snapshot["score"] == last["score"]
    assert snapshot["stats"] == last["match_stats"]
    assert snapshot["clock"] == {k: last["event"][k] for k in ("minute", "second", "period")}
    assert snapshot["events"][0]["id"] == last["event"]["id"]
    assert len(snapshot["events"]) == RECENT_EVENTS < len(updates)
    assert [e["id"] for e in snapshot["events"]] == [
        u["event"]["id"] for u in reversed(updates[-RECENT_EVENTS:])
    ]


def test_each_stream_gets_its_own_session(app):
    with TestClient(app) as client:
        ids = {stream(client)[0][1]["session_id"], stream(client)[0][1]["session_id"]}
    assert len(ids) == 2


def test_client_supplied_snapshot_is_ignored(app):
    forged = {"score": {"101": 9}, "events": [{"id": "forged"}], "clock": {"minute": 90}}
    with TestClient(app) as client:
        session_id = stream(client)[0][1]["session_id"]
        response = client.post(
            "/chat", json={"question": "Score?", "session_id": session_id, "snapshot": forged}
        )
    assert response.status_code == 200
    snapshot = app.state.chat.requests[0].snapshot
    assert "forged" not in json.dumps(snapshot)
    assert snapshot == app.state.sessions.get(session_id).snapshot()


def test_unknown_session_is_404_and_empty_session_is_409(app):
    with TestClient(app) as client:
        unknown = client.post("/chat", json={"question": "?", "session_id": "x" * 22})
        malformed = client.post("/chat", json={"question": "?", "session_id": "../etc"})
        legacy = client.post("/chat", json={"question": "?", "snapshot": {"events": []}})
        empty = app.state.sessions.create(client.get("/matches").json()[0])
        not_started = client.post("/chat", json={"question": "?", "session_id": empty.id})
    assert unknown.status_code == 404
    assert malformed.status_code == 422 and legacy.status_code == 422
    assert not_started.status_code == 409
    assert app.state.chat.requests == []


def test_ttl_expiry_and_capacity_eviction(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.sessions.time.monotonic", lambda: now[0])
    store = SessionStore(max_sessions=2, ttl_seconds=60)
    first, second = store.create({}), store.create({})
    store.get(first.id)  # Recently used sessions survive eviction.
    third = store.create({})
    assert store.get(second.id) is None
    assert store.get(first.id) and store.get(third.id)
    now[0] += 61
    assert store.get(first.id) is None and len(store) == 0
    assert SessionStore().max_sessions == 500 and SessionStore().ttl_seconds == 3 * 3600


def test_duplicate_events_are_recorded_once():
    session = MatchSession({"home_team": {}, "away_team": {}})
    event = {"id": "e1", "minute": 1, "second": 2, "period": 1, "type": {"name": "Pass"}}
    assert session.record(event, {"score": {}}) is True
    assert session.record(event, {"score": {}}) is False
    assert len(session.events) == 1


def test_session_never_holds_events_not_yet_emitted():
    """No future leakage: at every yielded frame the session knows only earlier frames."""
    emitted = []

    def check(frame, session):
        recorded = {event["id"] for event in session.events}
        assert recorded <= set(emitted)  # Nothing beyond what was handed out before.
        if "event: update" in frame:
            emitted.append(json.loads(frame.split("data: ", 1)[1])["event"]["id"])

    session, _ = synthetic_session(limit=120, collect=check)
    assert session.events[0]["id"] == emitted[-1]
    assert session.snapshot()["clock"]["minute"] <= 90
