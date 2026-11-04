import asyncio
import json
import re

import httpx
import pytest
from conftest import ScriptedModel, final, synthetic_session, tool_call, tool_results, unwrap
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

from app.agent.llm import build_model
from app.agent.service import MatchAgent
from app.agent.tools import DESCRIPTIONS, MatchTools
from app.analytics import PlayerAccumulator, is_progressive
from app.config import Settings
from app.main import create_app
from app.synthetic import SyntheticSource


@pytest.fixture(scope="module")
def half():
    """The synthetic match replayed to the end of its first half (~400 events)."""
    session, _ = synthetic_session(limit=400)
    return session


def ask(session, *script, question="What is happening?", mode="simple", **settings):
    model = ScriptedModel(script=list(script))
    agent = MatchAgent(Settings(gemini_api_key="unused", **settings), model)
    return asyncio.run(agent.ask(question, mode, session)), model


def test_first_half_danger_question_uses_compare_periods_and_player_stats(half):
    view = half.view()

    def pick_player(messages):
        # The "model" reads compare_periods output, then asks about the top xT player.
        best = max(
            (p for p in view.players.values() if p["team_id"] == 101),
            key=lambda p: p["xt_added"],
        )
        return tool_call(("get_player_stats", {"name": best["name"]}))

    def answer(messages):
        stats = tool_results(messages, "get_player_stats")[-1]
        return final(f"{stats['name']} added the most threat.", stats["recent_event_ids"][:1], 30)

    result, model = ask(
        half,
        tool_call(("compare_periods", {"start_min": 0, "end_min": 45})),
        pick_player,
        answer,
        question="Who was Northbridge's most dangerous player in the first half?",
    )
    assert [step["tool"] for step in result["tools_used"]] == [
        "compare_periods",
        "get_player_stats",
    ]
    assert result["tools_used"][0]["args"] == {"start_min": 0, "end_min": 45}
    assert set(model.bound_tools) == set(DESCRIPTIONS)
    window = tool_results(model.calls[1], "compare_periods")[0]
    assert window["inside"]["Northbridge FC"]["passes"] > 0
    assert result["orchestrator"] == "LangGraph" and result["evidence"]
    assert result["cited_event_ids"] == result["evidence_event_ids"]


def test_agent_picks_different_tools_for_different_questions(half):
    view = half.view()
    shot = next(r["event"]["id"] for r in reversed(view.history) if r.get("shot"))
    shot_answer, _ = ask(
        half,
        tool_call(("get_shot", {"event_id": shot}), ("find_sequence", {"event_id": shot})),
        final("A low-xG effort.", [shot], 40),
    )
    momentum_answer, _ = ask(half, tool_call(("get_momentum", {"window_min": 5})), final("Even."))
    assert [t["tool"] for t in shot_answer["tools_used"]] == ["get_shot", "find_sequence"]
    assert [t["tool"] for t in momentum_answer["tools_used"]] == ["get_momentum"]


def test_tool_loop_stops_after_four_rounds(half):
    script = [tool_call(("get_match_stats", {})) for _ in range(5)] + [final("Done.")]
    result, model = ask(half, *script)
    assert len(result["tools_used"]) == 4
    assert "Tool budget reached" in model.calls[4][-1].content


def test_fabricated_event_id_is_retried_then_rejected(half):
    with pytest.raises(HTTPException) as error:
        _, model = ask(half, final("Invented.", ["made-up"]), final("Again.", ["made-up"]))
    assert error.value.status_code == 502


def test_validator_feedback_lets_the_agent_correct_itself(half):
    latest = half.view().history[-1]["event"]["id"]
    result, model = ask(half, final("Invented.", ["made-up"]), final("Fixed.", [latest]))
    assert result["cited_event_ids"] == [latest]
    feedback = model.calls[1][-1]
    assert isinstance(feedback, HumanMessage) and "made-up" in feedback.content


def test_snapshot_minute_after_clock_is_rejected(half):
    with pytest.raises(HTTPException):
        ask(half, final("Later.", minute=95), final("Later.", minute=95))


def test_no_tool_returns_events_after_the_session_clock(half):
    future = synthetic_session(limit=401)[0].history[-1]["event"]["id"]
    view = half.view()
    half_ids = view.event_ids()
    assert future not in half_ids
    tools = MatchTools(view)
    some_shot = next(r["event"]["id"] for r in view.history if r.get("shot"))
    outputs = [
        tools.get_match_stats(),
        tools.get_recent_events(n=30),
        tools.get_player_stats("Northbridge 7"),
        tools.compare_periods(0, 90),
        tools.get_shot(some_shot),
        tools.get_shot(future),
        tools.find_sequence(view.history[-1]["event"]["id"]),
        tools.find_sequence(future),
        tools.get_momentum(45),
    ]
    text = json.dumps(outputs)
    mentioned = set(re.findall(r"synthetic-42-\d+", text))
    assert mentioned and mentioned <= half_ids
    assert future not in text
    clock = view.clock["minute"]
    assert all(e["minute"] <= clock for e in tools.get_recent_events(n=30)["events"])


def test_view_is_frozen_while_the_replay_continues():
    session, _ = synthetic_session(limit=50)
    view = session.view()
    later, _ = synthetic_session(limit=60)
    for record in later.history[50:]:
        session.history.append(record)
    assert len(MatchTools(view).get_recent_events(n=30)["events"]) == 30
    assert len(view.history) == 50


def test_tool_errors_go_back_to_the_model(half):
    result, model = ask(
        half,
        tool_call(("get_recent_events", {"team": "Nowhere Rovers"}), ("no_such_tool", {})),
        final("I could not find that team."),
    )
    errors = [unwrap(m.content)["error"] for m in model.calls[1][-3:-1]]  # [-1] is the sources note
    assert "Unknown team" in errors[0] and "Unknown tool" in errors[1]
    assert result["tools_used"] == []


def test_player_accumulator_and_progressive_passes():
    assert is_progressive([60, 40], [100, 40]) and not is_progressive([60, 40], [62, 40])
    players = PlayerAccumulator()
    update = {
        "event": {
            "id": "1",
            "period": 1,
            "type": {"name": "Pass"},
            "team": {"id": 1},
            "player": {"id": 9, "name": "Nine"},
            "location": [60, 40],
        },
        "event_details": {"pass": {}},
        "end_location": [100, 40],
        "momentum": {"action_value": 0.05},
    }
    players.consume(update)
    stats = players.snapshot()[9]
    assert (stats["passes"], stats["progressive_passes"], stats["touches"]) == (1, 1, 1)
    assert stats["xt_added"] == 0.05


@pytest.mark.parametrize(
    "provider,cls",
    [("ollama", "ChatOllama"), ("foundry", "ChatOpenAI"), ("gemini", "ChatGoogleGenerativeAI")],
)
def test_providers_build_without_network(provider, cls):
    settings = Settings(
        chat_provider=provider,
        gemini_api_key="k",
        foundry_endpoint="https://example.openai.azure.com",
        foundry_deployment="dep",
        foundry_api_key="az",
    )
    model = build_model(settings)
    assert type(model).__name__ == cls
    if provider == "ollama":
        assert model.model == "qwen2.5:7b-instruct" and model.base_url == "http://127.0.0.1:11434"
    with pytest.raises(HTTPException):
        build_model(Settings(gemini_api_key="", chat_fallback_offline=False))
    # Phase 6: without a key the public demo falls back to the labelled offline baseline.
    assert type(build_model(Settings(gemini_api_key=""))).__name__ == "OfflineAnalyst"


class Upstream(Exception):
    def __init__(self, status):
        super().__init__("secret upstream detail")
        self.status_code = status


def wrapped_connect_error():
    try:
        raise httpx.ConnectError("secret", request=httpx.Request("POST", "http://x"))
    except httpx.ConnectError as error:
        try:
            raise RuntimeError("secret wrapper") from error
        except RuntimeError as wrapper:
            return wrapper


@pytest.mark.parametrize(
    "make,status",
    [
        (lambda: Upstream(429), 429),
        (lambda: Upstream(403), 503),
        (lambda: Upstream(500), 502),
        (wrapped_connect_error, 502),
        (lambda: httpx.ReadTimeout("secret"), 504),
    ],
)
def test_provider_errors_are_sanitized(half, make, status):
    def fail(messages):
        raise make()

    with pytest.raises(HTTPException) as error:
        ask(half, fail)
    assert error.value.status_code == status and "secret" not in error.value.detail


class ShortSource(SyntheticSource):
    async def events(self, match_id):
        return (await super().events(match_id))[:150]


def test_chat_endpoint_returns_tool_trace(monkeypatch):
    application = create_app()
    application.state.source = ShortSource()
    application.state.agent = MatchAgent(
        Settings(gemini_api_key="x"),
        ScriptedModel(script=[tool_call(("get_match_stats", {})), final("Level so far.")]),
    )
    with TestClient(application) as client:
        body = client.get("/matches/1/stream", params={"speed": 1000}).text
        session_id = json.loads(body.split("data: ", 1)[1].split("\n")[0])["session_id"]
        answer = client.post("/chat", json={"question": "Score?", "session_id": session_id})
    assert answer.status_code == 200
    assert answer.json()["tools_used"] == [{"tool": "get_match_stats", "args": {}}]


def test_maf_setting_still_runs_the_original_workflow(monkeypatch):
    monkeypatch.setenv("GAME_AGENT", "maf")
    monkeypatch.setenv("GAME_GEMINI_API_KEY", "test-key")
    application = create_app()
    application.state.source = ShortSource()

    def handler(request):
        events = json.loads(json.loads(request.content)["input"])["snapshot"]["events"]
        text = json.dumps({"text": "Original.", "evidence_event_ids": [events[0]["id"]]})
        return httpx.Response(200, json={"outputs": [{"type": "text", "text": text}]})

    application.state.chat.transport = httpx.MockTransport(handler)
    with TestClient(application) as client:
        body = client.get("/matches/1/stream", params={"speed": 1000}).text
        session_id = json.loads(body.split("data: ", 1)[1].split("\n")[0])["session_id"]
        answer = client.post("/chat", json={"question": "Score?", "session_id": session_id})
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["orchestrator"] == "Microsoft Agent Framework"
    assert [t["tool"] for t in data["tools_used"]] == [
        "get_match_stats",
        "get_recent_events",
        "get_player_summary",
    ]


def test_invalid_json_is_repaired_by_the_structured_answer_model():
    import asyncio

    from conftest import ScriptedModel, final, synthetic_session, tool_call
    from langchain_core.messages import AIMessage

    from app.agent.graph import AgentContext, run_agent
    from app.sessions import SessionView  # noqa: F401

    session, _ = synthetic_session(limit=60)
    model = ScriptedModel(script=[tool_call(("get_match_stats", {})), AIMessage("Sure! {text:")])
    structured = ScriptedModel(script=[final("Scores are level so far.")])
    context = AgentContext(answer_model=structured)
    result = asyncio.run(run_agent(model, session.view(), "Score?", "simple", context=context))
    assert result["text"] == "Scores are level so far."
    assert len(structured.calls) == 1 and result["usage"]["model_calls"] == 3


def test_valid_json_skips_the_structured_answer_model():
    import asyncio

    from conftest import ScriptedModel, final, synthetic_session

    from app.agent.graph import AgentContext, run_agent

    session, _ = synthetic_session(limit=60)
    structured = ScriptedModel()
    context = AgentContext(answer_model=structured)
    result = asyncio.run(
        run_agent(
            ScriptedModel(script=[final("Level.")]),
            session.view(),
            "Score?",
            "simple",
            context=context,
        )
    )
    assert result["text"] == "Level." and structured.calls == []


def test_ollama_answer_model_uses_the_answer_json_schema():
    from app.agent.graph import AgentAnswer
    from app.agent.llm import build_answer_model
    from app.config import Settings

    model = build_answer_model(Settings(chat_provider="ollama", ollama_model="qwen2.5:7b"))
    assert model.format == AgentAnswer.model_json_schema()
    assert build_answer_model(Settings(gemini_api_key="k")) is None
