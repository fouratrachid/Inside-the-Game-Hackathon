"""The LangGraph chat service.

Per question: input guardrails → cache → budget → agent on a frozen session view (traced) →
usage and cost accounting → sanitized errors. `ask` returns one JSON answer; `stream` yields
SSE-ready events (token, reset, final, error).
"""

import asyncio
import logging

import httpx
from fastapi import HTTPException
from langchain_core.language_models import BaseChatModel

from app.agent.graph import AgentContext, AgentFailure, run_agent, stream_agent
from app.agent.llm import (
    PROVIDER_LABELS,
    build_answer_model,
    build_model,
    effective_provider,
    model_name,
)
from app.config import Settings
from app.guardrails import check_question
from app.observability import Tracer
from app.sessions import MatchSession
from app.usage import DEFAULT_PRICES, AnswerCache

logger = logging.getLogger(__name__)


def _chain(error: BaseException):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def _status(error: BaseException) -> int | None:
    for item in _chain(error):
        for attribute in ("status_code", "code"):
            value = getattr(item, attribute, None)
            if isinstance(value, int) and 100 <= value <= 599:
                return value
        response = getattr(item, "response", None)
        if isinstance(getattr(response, "status_code", None), int):
            return response.status_code
    return None


def provider_error(error: Exception) -> HTTPException:
    """Translate any provider SDK exception into a short error that leaks nothing."""
    status = _status(error)
    logger.warning("Agent model call failed: %s (HTTP %s)", type(error).__name__, status)
    if any(isinstance(e, TimeoutError | httpx.TimeoutException) for e in _chain(error)):
        return HTTPException(504, "The model took too long to answer. Please try again.")
    if status == 400:
        return HTTPException(
            502, "The model rejected the request settings. Check the model configuration."
        )
    if status in {401, 403}:
        return HTTPException(
            503, "The model rejected the API key or model access. Check the server configuration."
        )
    if status == 404:
        return HTTPException(
            503, "The configured model is unavailable. Check the server model configuration."
        )
    if status == 429:
        return HTTPException(
            429, "The model's request quota is temporarily exhausted. Try again later."
        )
    if any(isinstance(e, httpx.ConnectError | ConnectionError) for e in _chain(error)):
        return HTTPException(
            502,
            "The server could not connect to the model provider. "
            "Check the provider URL and the server's internet or proxy connection.",
        )
    return HTTPException(502, "The model is temporarily unavailable. Please try again.")


FAILED_ANSWER = "The model returned an unsupported answer. Please try again."


class MatchAgent:
    def __init__(
        self,
        settings: Settings,
        model: BaseChatModel | None = None,
        tracer: Tracer | None = None,
        knowledge=None,
    ):
        self.settings = settings
        self._model = model
        self._injected = model is not None
        self._answer_model = None
        self.tracer = tracer or Tracer()
        self.knowledge = knowledge
        self.cache = AnswerCache(settings.cache_max_entries, settings.cache_ttl_seconds)
        self.prices = {**DEFAULT_PRICES, **settings.model_prices}

    @property
    def provider(self) -> str:
        return PROVIDER_LABELS[effective_provider(self.settings)]

    def model(self) -> BaseChatModel:
        if self._model is None:
            self._model = build_model(self.settings)
        return self._model

    def answer_model(self) -> BaseChatModel | None:
        """Structured-output model for the final answer; skipped when a model was injected."""
        if self._injected:
            return None
        if self._answer_model is None:
            self._answer_model = build_answer_model(self.settings)
        return self._answer_model

    def _secrets(self) -> list[str]:
        s = self.settings
        return [
            value.get_secret_value()
            for value in (
                s.gemini_api_key,
                s.foundry_api_key,
                s.langfuse_secret_key,
                s.langfuse_public_key,
            )
            if value.get_secret_value()
        ]

    def _budget(self) -> float | None:
        return self.settings.session_budget_usd or None

    def _prepare(self, question: str, mode: str, session: MatchSession, kind: str):
        """Shared pre-flight: trace, guardrails, cache and budget. Returns (early, run)."""
        view = session.view()
        if view.clock is None:
            raise HTTPException(409, "The replay has not emitted any events yet.")
        session.usage.questions += 1
        label = model_name(self.settings)
        root = self.tracer.trace(
            kind,
            input={"question": question, "mode": mode},
            session_id=session.id,
            tags=[
                "langgraph",
                effective_provider(self.settings),
                f"match:{view.match.get('match_id')}",
            ],
            metadata={
                "match_id": view.match.get("match_id"),
                "agent": "langgraph",
                "provider": effective_provider(self.settings),
                "model": label,
                "clock": view.clock,
            },
        )
        check = check_question(question)
        if check.flags:
            root.event("guardrail.input", flags=check.flags)
        base = {
            "orchestrator": "LangGraph",
            "provider": self.provider,
            "model": label,
            "mode": mode,
            "as_of": view.clock,
            "guard_flags": check.flags,
        }
        if check.refusal:
            session.usage.blocked += 1
            answer = {
                **base,
                "text": check.refusal,
                "refused": True,
                "cited_event_ids": [],
                "evidence_event_ids": [],
                "evidence": [],
                "cited_sources": [],
                "snapshot_minute": view.clock["minute"],
                "tools_used": [],
                "cached": False,
                "usage": {},
            }
            root.end(output={"refused": True, "flags": check.flags})
            return self._with_session(answer, session), None
        key = AnswerCache.key(question, view.match.get("match_id"), view.clock, mode, label)
        cached = self.cache.get(key)
        if cached is not None:
            session.usage.cache_hits += 1
            root.event("cache.hit")
            root.end(output={"cached": True})
            return self._with_session({**cached, "cached": True, "usage": {}}, session), None
        budget = self._budget()
        if budget is not None and session.usage.cost_usd >= budget:
            session.usage.blocked += 1
            root.end(output={"blocked": "budget"}, level="WARNING")
            raise HTTPException(402, "This replay's AI budget is used up. Start a new replay.")
        context = AgentContext(
            tracer=self.tracer,
            root=root,
            knowledge=self.knowledge,
            model_label=label,
            prices=self.prices,
            secrets=self._secrets(),
            flags=check.flags,
            answer_model=self.answer_model(),
        )
        return None, (view, context, key, base, root)

    def _with_session(self, answer: dict, session: MatchSession) -> dict:
        return {**answer, "session_usage": session.usage.as_dict(self._budget())}

    def _finish(self, result: dict, view, key, base, root, session: MatchSession) -> dict:
        session.usage.add(result["usage"])
        summaries = {r["event"].get("id"): r["summary"] for r in view.history}
        cited = result["cited_event_ids"]
        answer = {
            **base,
            "text": result["text"],
            "cited_event_ids": cited,
            "evidence_event_ids": cited,  # Name used by the original UI.
            "evidence": [summaries[i] for i in cited],
            "cited_sources": result.get("cited_sources", []),
            "snapshot_minute": result["snapshot_minute"],
            "tools_used": result["tools_used"],
            "usage": result["usage"],
            "cached": False,
        }
        self.cache.put(key, {k: v for k, v in answer.items() if k != "usage"})
        root.end(
            output={"text": answer["text"], "cited": cited, "tools": result["tools_used"]},
            usage={k: v for k, v in result["usage"].items() if k.endswith("tokens")},
            cost=result["usage"].get("cost_usd"),
        )
        return self._with_session(answer, session)

    def _error(self, error: Exception, root, session: MatchSession) -> HTTPException:
        if isinstance(error, TimeoutError):
            failure = HTTPException(504, "The model took too long to answer. Please try again.")
        elif isinstance(error, AgentFailure):
            logger.warning("Agent produced no valid answer: %s", str(error)[:200])
            session.usage.add(getattr(error, "usage", {}))
            failure = HTTPException(502, FAILED_ANSWER)
            root.event("guardrail.output", problem=str(error)[:300], guard=error.guard)
        elif isinstance(error, HTTPException):
            failure = error
        else:  # Provider SDKs raise many types; never leak their text.
            failure = provider_error(error)
        root.end(output={"status": failure.status_code}, level="ERROR")
        return failure

    async def ask(self, question: str, mode: str, session: MatchSession) -> dict:
        early, run = self._prepare(question, mode, session, "chat")
        if early is not None:
            return early
        view, context, key, base, root = run
        try:
            model = self.model()
            async with asyncio.timeout(self.settings.chat_timeout_seconds):
                result = await run_agent(
                    model, view, question, mode, self.settings.agent_max_tool_rounds, context
                )
        except Exception as error:
            raise self._error(error, root, session) from None
        return self._finish(result, view, key, base, root, session)

    async def stream(self, question: str, mode: str, session: MatchSession):
        """Yield (event, data) pairs: token*, reset?, then final or error."""
        try:
            early, run = self._prepare(question, mode, session, "chat.stream")
        except HTTPException as error:
            yield "error", {"status": error.status_code, "detail": error.detail}
            return
        if early is not None:
            yield "token", {"text": early["text"]}
            yield "final", early
            return
        view, context, key, base, root = run
        try:
            model = self.model()
            async with asyncio.timeout(self.settings.chat_timeout_seconds):
                async for kind, data in stream_agent(
                    model, view, question, mode, self.settings.agent_max_tool_rounds, context
                ):
                    if kind == "token":
                        yield "token", {"text": data}
                    elif kind == "reset":
                        yield "reset", {}
                    else:
                        yield "final", self._finish(data, view, key, base, root, session)
        except Exception as error:
            failure = self._error(error, root, session)
            yield "error", {"status": failure.status_code, "detail": failure.detail}
