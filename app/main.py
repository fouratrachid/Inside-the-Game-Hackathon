"""HTTP entry point: replay streams, server-side match sessions and match chat."""

from pathlib import Path
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.agent.service import MatchAgent
from app.chat import ChatQuery, ChatRequest, MatchChat
from app.config import Settings
from app.explanations import Audience, ExplanationProvider
from app.replay import replay
from app.sessions import SessionStore
from app.source import StatsBombSource


def create_app() -> FastAPI:
    settings = Settings()
    application = FastAPI(title=settings.app_name, version="0.1.0")
    application.state.source = StatsBombSource()
    application.state.settings = settings
    application.state.chat = MatchChat(settings)
    application.state.agent = MatchAgent(settings)
    application.state.explanations = ExplanationProvider(settings)
    application.state.sessions = SessionStore()
    static = Path(__file__).parent / "static"
    application.mount("/static", StaticFiles(directory=static), name="static")

    @application.get("/", include_in_schema=False)
    async def home():
        return FileResponse(static / "overlay.html")

    @application.get("/matchroom", include_in_schema=False)
    async def matchroom():
        return FileResponse(static / "index.html")

    @application.get("/overlay", include_in_schema=False)
    async def overlay():
        return RedirectResponse("/", status_code=308)

    @application.post("/chat", tags=["match intelligence"])
    async def chat(payload: ChatQuery):
        session = application.state.sessions.get(payload.session_id)
        if session is None:
            raise HTTPException(404, "Replay session not found or expired. Restart the replay.")
        snapshot = session.snapshot()
        if snapshot is None:
            raise HTTPException(409, "The replay has not emitted any events yet.")
        if settings.agent == "langgraph":
            return await application.state.agent.ask(payload.question, payload.mode, session.view())
        if settings.chat_provider == "ollama":
            raise HTTPException(503, "The original workflow supports Gemini or Foundry only.")
        try:
            request = ChatRequest(question=payload.question, mode=payload.mode, snapshot=snapshot)
        except ValidationError:
            raise HTTPException(500, "Could not prepare the match context.") from None
        answer = await application.state.chat.ask(request)
        # Same trace shape as the LangGraph agent: [{tool, args}].
        tools = answer.get("tools_used") or []
        return {**answer, "tools_used": [{"tool": name, "args": {}} for name in tools]}

    async def load(awaitable):
        try:
            return await awaitable
        except httpx.HTTPStatusError as exc:
            raise HTTPException(502, "StatsBomb returned an unsuccessful response") from exc
        except (httpx.RequestError, ValueError) as exc:
            raise HTTPException(502, "Could not load StatsBomb data") from exc

    @application.get("/matches", tags=["replay"])
    async def matches():
        return await load(application.state.source.matches())

    @application.get("/matches/{match_id}/stream", tags=["replay"])
    async def stream(
        match_id: int,
        request: Request,
        speed: Annotated[float, Query(ge=0.1, le=1000, allow_inf_nan=False)] = 1,
        audience: Audience = "casual",
        insights: bool = False,
    ):
        catalog = await load(application.state.source.matches())
        match = next((m for m in catalog if m["match_id"] == match_id), None)
        if match is None:
            raise HTTPException(404, "Match not found in selected source")
        events = await load(application.state.source.events(match_id))
        session = application.state.sessions.create(match)
        return StreamingResponse(
            replay(
                events,
                match,
                speed,
                request.is_disconnected,
                application.state.explanations if insights else None,
                audience,
                session,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
