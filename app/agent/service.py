"""The LangGraph chat service: run the agent on a frozen session view, map errors safely."""

import asyncio
import logging

import httpx
from fastapi import HTTPException
from langchain_core.language_models import BaseChatModel

from app.agent.graph import AgentFailure, run_agent
from app.agent.llm import PROVIDER_LABELS, build_model, model_name
from app.config import Settings
from app.sessions import SessionView

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


class MatchAgent:
    def __init__(self, settings: Settings, model: BaseChatModel | None = None):
        self.settings = settings
        self._model = model

    def model(self) -> BaseChatModel:
        if self._model is None:
            self._model = build_model(self.settings)
        return self._model

    async def ask(self, question: str, mode: str, view: SessionView) -> dict:
        if view.clock is None:
            raise HTTPException(409, "The replay has not emitted any events yet.")
        model = self.model()
        try:
            async with asyncio.timeout(self.settings.chat_timeout_seconds):
                result = await run_agent(
                    model, view, question, mode, self.settings.agent_max_tool_rounds
                )
        except TimeoutError:
            raise HTTPException(
                504, "The model took too long to answer. Please try again."
            ) from None
        except AgentFailure as failure:
            logger.warning("Agent produced no valid answer: %s", str(failure)[:200])
            raise HTTPException(
                502, "The model returned an unsupported answer. Please try again."
            ) from None
        except HTTPException:
            raise
        except Exception as error:  # Provider SDKs raise many types; never leak their text.
            raise provider_error(error) from None
        summaries = {r["event"].get("id"): r["summary"] for r in view.history}
        cited = result["cited_event_ids"]
        return {
            "text": result["text"],
            "cited_event_ids": cited,
            "evidence_event_ids": cited,  # Name used by the original UI.
            "evidence": [summaries[i] for i in cited],
            "snapshot_minute": result["snapshot_minute"],
            "as_of": view.clock,
            "tools_used": result["tools_used"],
            "orchestrator": "LangGraph",
            "provider": PROVIDER_LABELS[self.settings.chat_provider],
            "model": model_name(self.settings),
            "mode": mode,
        }
