"""Shared test helpers: instant replays on a virtual clock (no sleeping, no network)."""

import asyncio
from unittest import mock

import pytest

from app.replay import replay_updates
from app.sessions import MatchSession
from app.synthetic import SyntheticSource


@pytest.fixture(autouse=True)
def _offline_settings(monkeypatch):
    """Tests never write trace logs into the repository or build a real embedder."""
    monkeypatch.setenv("GAME_TRACE_LOG", "")
    monkeypatch.setenv("GAME_RAG_EMBEDDER", "hash")


async def run_replay(events, match, session, collect=None):
    """Replay exactly as production paces it, but on a virtual clock so it is instant."""
    clock = [0.0]

    async def sleep(seconds):
        clock[0] += seconds

    async def connected():
        return False

    frames = []
    with (
        mock.patch("app.replay.time.monotonic", lambda: clock[0]),
        mock.patch("app.replay.asyncio.sleep", sleep),
    ):
        async for frame in replay_updates(events, match, 1, connected, session):
            frames.append(frame)
            if collect:
                collect(frame, session)
    return frames


def synthetic_session(limit=None, collect=None):
    """Replay the seeded synthetic match (optionally its first `limit` events)."""

    async def run():
        source = SyntheticSource()
        match = (await source.matches())[0]
        events = (await source.events(match["match_id"]))[:limit]
        session = MatchSession(match)
        frames = await run_replay(events, match, session, collect)
        return session, frames

    return asyncio.run(run())


# Fake LLM for agent tests (no API key, no network) ----------------------------------------
import itertools  # noqa: E402
import json  # noqa: E402

from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from pydantic import Field  # noqa: E402

_call_ids = itertools.count(1)


class ScriptedModel(BaseChatModel):
    """Plays back AI turns. Each step is an AIMessage or a callable(messages) -> AIMessage."""

    script: list = Field(default_factory=list)
    calls: list = Field(default_factory=list)
    bound_tools: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = [tool.name for tool in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(list(messages))
        if not self.script:
            raise AssertionError("The scripted model ran out of turns")
        step = self.script.pop(0)
        message = step(messages) if callable(step) else step
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(*requests) -> AIMessage:
    """An AI turn requesting tools: tool_call(("get_match_stats", {}), ...)."""
    return AIMessage(
        content="",
        tool_calls=[{"name": n, "args": a, "id": f"c{next(_call_ids)}"} for n, a in requests],
    )


def final(text: str, ids=(), minute: int = 0) -> AIMessage:
    return AIMessage(
        content=json.dumps({"text": text, "cited_event_ids": list(ids), "snapshot_minute": minute})
    )


def unwrap(content: str):
    """Tool results are delimited as <tool_result ...> JSON </tool_result> (Phase 4)."""
    return json.loads(content.split("\n", 1)[1].rsplit("\n", 1)[0])


def tool_results(messages, name: str) -> list:
    return [unwrap(m.content) for m in messages if isinstance(m, ToolMessage) and m.name == name]
