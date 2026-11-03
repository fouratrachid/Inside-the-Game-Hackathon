import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.llm import effective_provider
from app.catalog import CombinedSource, build_source
from app.config import Settings
from app.main import create_app
from app.source import StatsBombSource
from app.synthetic import SyntheticSource


class ShortSource(SyntheticSource):
    async def events(self, match_id):
        return (await super().events(match_id))[:120]


def session_id(body: str) -> str:
    return json.loads(body.split("data: ", 1)[1].split("\n")[0])["session_id"]


@pytest.fixture
def public_demo(monkeypatch):
    """The hosted configuration with no API key and no network: synthetic + offline chat."""
    monkeypatch.setenv("GAME_SOURCE", "synthetic")
    monkeypatch.setenv("GAME_GEMINI_API_KEY", "")
    monkeypatch.setenv("GAME_RAG_ENABLED", "false")
    return create_app()


def test_public_demo_works_without_a_key(public_demo):
    with TestClient(public_demo) as client:
        matches = client.get("/matches").json()
        assert [m["match_id"] for m in matches] == [1]
        sid = session_id(client.get("/matches/1/stream", params={"speed": 1000}).text)
        answer = client.post("/chat", json={"question": "What is the score?", "session_id": sid})
    assert answer.status_code == 200
    data = answer.json()
    assert data["provider"] == "Offline rule-based baseline" and data["text"].startswith("It is")


def test_timeline_notes_have_server_side_cooldowns(public_demo, monkeypatch):
    monkeypatch.setenv("GAME_NOTE_MAX_PER_SESSION", "2")
    monkeypatch.setenv("GAME_NOTE_MIN_INTERVAL_SECONDS", "0")
    app = create_app()
    app.state.source = ShortSource()
    with TestClient(app) as client:
        sid = session_id(client.get("/matches/1/stream", params={"speed": 1000}).text)
        note = {"question": "Interpret the match.", "session_id": sid, "purpose": "note"}
        codes = [client.post("/chat", json=note).status_code for _ in range(3)]
        ask = client.post("/chat", json={"question": "Score?", "session_id": sid})
    assert codes == [200, 200, 429] and ask.status_code == 200


def test_note_spacing(public_demo):
    public_demo.state.source = ShortSource()
    with TestClient(public_demo) as client:
        sid = session_id(client.get("/matches/1/stream", params={"speed": 1000}).text)
        note = {"question": "Interpret the match.", "session_id": sid, "purpose": "note"}
        first, second = client.post("/chat", json=note), client.post("/chat", json=note)
    assert first.status_code == 200 and second.status_code == 429
    assert "spaced" in second.json()["detail"]


def test_combined_source_survives_statsbomb_outage(monkeypatch):
    async def down(self):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(StatsBombSource, "matches", down)
    source = CombinedSource()
    matches = asyncio.run(source.matches())
    assert [m["match_id"] for m in matches] == [1]
    assert asyncio.run(source.events(1))[0]["id"].startswith("synthetic-42")
    assert isinstance(build_source(Settings(source="both")), CombinedSource)
    assert isinstance(build_source(Settings(source="statsbomb")), StatsBombSource)


def test_offline_fallback_and_session_limits_are_configurable(monkeypatch):
    assert effective_provider(Settings(gemini_api_key="")) == "offline"
    assert effective_provider(Settings(gemini_api_key="k")) == "gemini"
    assert effective_provider(Settings(gemini_api_key="", chat_fallback_offline=False)) == "gemini"
    monkeypatch.setenv("GAME_MAX_SESSIONS", "7")
    monkeypatch.setenv("GAME_SESSION_TTL_SECONDS", "60")
    store = create_app().state.sessions
    assert (store.max_sessions, store.ttl_seconds) == (7, 60)
