import asyncio
import json

from conftest import ScriptedModel, final, synthetic_session, tool_call

from app.agent.service import MatchAgent
from app.config import Settings
from app.observability import JsonlBackend, LangfuseBackend, Tracer, build_tracer


class RecordingBackend:
    def __init__(self):
        self.started, self.ended = [], []

    def start(self, span):
        self.started.append(span)

    def end(self, span, handle):
        self.ended.append(span)


def run(tracer, *script, question="Who is pressing?"):
    session, _ = synthetic_session(limit=120)
    agent = MatchAgent(Settings(gemini_api_key="k"), ScriptedModel(script=list(script)), tracer)
    return asyncio.run(agent.ask(question, "simple", session)), session


def test_tracing_is_a_noop_without_keys_or_log():
    tracer = build_tracer(Settings(trace_log="", langfuse_public_key="", langfuse_secret_key=""))
    assert tracer.backends == [] and not tracer.enabled
    answer, _ = run(tracer, final("Fine."))
    assert answer["text"] == "Fine."


def test_every_tool_call_and_model_call_produces_a_span():
    backend = RecordingBackend()
    answer, session = run(
        Tracer([backend]),
        tool_call(("get_match_stats", {}), ("get_recent_events", {"n": 3})),
        tool_call(("get_momentum", {"window_min": 5})),
        final("Even."),
    )
    names = [span.name for span in backend.ended]
    tools = [span for span in backend.ended if span.kind == "tool"]
    assert [span.name for span in tools] == ["get_match_stats", "get_recent_events", "get_momentum"]
    assert tools[1].input == {"n": 3} and tools[1].output["size"] > 0
    assert all(span.duration_ms is not None for span in backend.ended)
    assert names.count("agent") == 3 and "validator" in names
    root = backend.ended[-1]
    assert root.parent is None and root.metadata["session_id"] == session.id
    assert {"langgraph", "gemini"} <= set(root.metadata["tags"])
    assert root.metadata["match_id"] == 1 and root.metadata["agent"] == "langgraph"


def test_jsonl_backend_writes_one_line_per_trace(tmp_path):
    path = tmp_path / "traces.jsonl"
    run(Tracer([JsonlBackend(path)]), tool_call(("get_match_stats", {})), final("Ok."))
    run(Tracer([JsonlBackend(path)]), final("Again."), question="Score so far?")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(lines) == 2
    first = lines[0]
    assert first["session_id"] and first["name"] == "chat"
    assert any(s["kind"] == "tool" and s["name"] == "get_match_stats" for s in first["spans"])
    assert any(s["kind"] == "generation" for s in first["spans"])


class FakeObservation:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def start_observation(self, **kwargs):
        self.log.append(("child", self.name, kwargs["name"], kwargs["as_type"]))
        return FakeObservation(self.log, kwargs["name"])

    def update(self, **kwargs):
        self.log.append(("update", self.name, sorted(kwargs)))

    def end(self):
        self.log.append(("end", self.name))


class FakeLangfuse(FakeObservation):
    def __init__(self):
        super().__init__([], "client")

    def flush(self):
        self.log.append(("flush",))


def test_langfuse_backend_mirrors_the_span_tree_without_network():
    client = FakeLangfuse()
    run(
        Tracer([LangfuseBackend("pk", "sk", "http://x", client=client)]),
        tool_call(("get_match_stats", {})),
        final("Ok."),
    )
    log = client.log
    assert ("child", "client", "chat", "agent") in log
    assert ("child", "chat", "get_match_stats", "tool") in log
    assert ("child", "chat", "agent", "generation") in log
    assert log[-1] == ("flush",) and ("end", "chat") in log
