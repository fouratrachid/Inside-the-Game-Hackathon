import json

import pytest
from conftest import ScriptedModel, final, tool_call
from fastapi.testclient import TestClient

from app.agent.graph import TextFieldStreamer
from app.agent.service import MatchAgent
from app.config import Settings
from app.main import create_app
from app.synthetic import SyntheticSource
from app.usage import AnswerCache, SessionUsage, cost_usd


class ShortSource(SyntheticSource):
    async def events(self, match_id):
        return (await super().events(match_id))[:120]


def priced(text, input_tokens=1000, output_tokens=500, minute=0):
    message = final(text, minute=minute)
    message.usage_metadata = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    return message


def sse(body):
    out = []
    for block in body.split("\n\n"):
        kind = next((x[7:] for x in block.splitlines() if x.startswith("event: ")), None)
        data = next((x[6:] for x in block.splitlines() if x.startswith("data: ")), None)
        if kind:
            out.append((kind, json.loads(data)))
    return out


@pytest.fixture
def client_for(monkeypatch):
    def build(*script, **settings):
        for key, value in settings.items():
            monkeypatch.setenv(f"GAME_{key.upper()}", str(value))
        application = create_app()
        application.state.source = ShortSource()
        model = ScriptedModel(script=list(script))
        application.state.agent = MatchAgent(
            Settings(gemini_api_key="k", model_prices={"gemini-3.8-flash": (0.3, 2.5)}, **settings),
            model,
        )
        client = TestClient(application)
        body = client.get("/matches/1/stream", params={"speed": 1000}).text
        sid = json.loads(body.split("data: ", 1)[1].split("\n")[0])["session_id"]
        return client, sid, model

    return build


def test_stream_sends_tokens_then_final_with_citations_trace_and_cost(client_for):
    client, sid, _ = client_for(tool_call(("get_match_stats", {})), priced("Northbridge lead."))
    events = sse(
        client.post("/chat/stream", json={"question": "Who leads?", "session_id": sid}).text
    )
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "token" and kinds[-1] == "final" and "error" not in kinds
    assert "".join(d["text"] for k, d in events if k == "token") == "Northbridge lead."
    final_event = events[-1][1]
    assert final_event["tools_used"] == [{"tool": "get_match_stats", "args": {}}]
    assert final_event["usage"]["input_tokens"] == 1000
    assert final_event["usage"]["cost_usd"] == pytest.approx(0.00155)
    assert final_event["session_usage"]["cost_usd"] == pytest.approx(0.00155)


def test_stream_replaces_text_with_error_when_validation_fails(client_for):
    client, sid, _ = client_for(final("Bad.", ["invented"]), final("Bad.", ["invented"]))
    events = sse(client.post("/chat/stream", json={"question": "?", "session_id": sid}).text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "token" and "reset" in kinds and kinds[-1] == "error"
    assert events[-1][1]["status"] == 502


def test_cache_hit_and_miss(client_for):
    client, sid, model = client_for(priced("First."), priced("Other question."))
    ask = lambda q: client.post("/chat", json={"question": q, "session_id": sid}).json()  # noqa: E731
    first, again, other = ask("Who leads?"), ask("  who LEADS? "), ask("Any shots?")
    assert first["cached"] is False and again["cached"] is True and again["text"] == "First."
    assert other["text"] == "Other question." and len(model.calls) == 2
    usage = client.get(f"/sessions/{sid}/usage").json()
    assert usage["cache_hits"] == 1 and usage["questions"] == 3 and usage["model_calls"] == 2


def test_budget_blocks_further_model_calls(client_for):
    client, sid, model = client_for(
        priced("Expensive.", 1_000_000, 0), priced("Never sent."), session_budget_usd=0.2
    )
    first = client.post("/chat", json={"question": "Q1?", "session_id": sid})
    second = client.post("/chat", json={"question": "Q2?", "session_id": sid})
    assert first.status_code == 200 and second.status_code == 402
    usage = client.get(f"/sessions/{sid}/usage").json()
    assert usage["cost_usd"] == pytest.approx(0.3) and usage["budget_remaining_usd"] == 0
    assert usage["blocked"] == 1 and len(model.calls) == 1
    assert client.get("/sessions/unknown-session-id-123/usage").status_code == 404


def test_cost_arithmetic_and_usage_totals():
    prices = {"m": (0.30, 2.50)}
    assert cost_usd("m", 1_000_000, 500_000, prices) == pytest.approx(1.55)
    assert cost_usd("m", 0, 0, prices) == 0
    assert cost_usd("unpriced", 10_000, 10_000, prices) == 0
    usage = SessionUsage()
    usage.add({"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001, "model_calls": 2})
    usage.add({"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0005, "model_calls": 1})
    assert (usage.input_tokens, usage.model_calls, usage.cost_usd) == (11, 3, 0.0015)
    assert usage.as_dict(0.01)["budget_remaining_usd"] == pytest.approx(0.0085)


def test_cache_keys_and_ttl(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("app.usage.time.monotonic", lambda: now[0])
    cache = AnswerCache(max_entries=2, ttl_seconds=10)
    key = AnswerCache.key("Who leads?", 1, {"period": 1, "minute": 10}, "simple", "g")
    assert key == AnswerCache.key("who leads", 1, {"period": 1, "minute": 10}, "simple", "g")
    assert key != AnswerCache.key("who leads", 1, {"period": 1, "minute": 11}, "simple", "g")
    cache.put(key, {"text": "x"})
    assert cache.get(key) == {"text": "x"}
    now[0] = 11
    assert cache.get(key) is None


def test_text_field_streamer_handles_split_chunks_and_escapes():
    streamer = TextFieldStreamer()
    pieces = ['{"te', 'xt": "Line \\"one', '\\"\\nTwo', '", "cited_event_ids": []}']
    assert "".join(streamer.feed(p) for p in pieces) == 'Line "one"\nTwo'
