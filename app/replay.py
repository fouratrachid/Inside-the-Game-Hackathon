"""Independent replay sessions emitting incremental analytics over SSE."""

import asyncio
import json
import time
from copy import deepcopy

from app.analytics import MatchAnalytics, period_seconds
from app.explanations import Audience, ExplanationProvider
from app.sessions import MatchSession


def sse(kind: str, payload: dict, event_id: str | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}event: {kind}\ndata: {json.dumps(payload, allow_nan=False)}\n\n"


async def replay_updates(
    events: list[dict],
    match: dict,
    speed: float,
    disconnected,
    session: MatchSession | None = None,
):
    state = MatchAnalytics(match["home_team"]["id"], match["away_team"]["id"])
    yield sse(
        "match",
        {
            **match,
            **({"session_id": session.id} if session else {}),
            "source": match.get("source", "statsbomb_historical"),
            "simulated_live": True,
            "speed": speed,
            "coordinates": {
                "length": 120,
                "width": 80,
                "attack_direction": "+x for both teams (raw StatsBomb coordinates)",
                "display_convention": "home +x in period 1; opposite ends each subsequent half",
            },
        },
    )
    previous_period = None
    origin = time.monotonic()
    elapsed = 0.0
    previous_clock = 0.0
    for event in events:
        clock = period_seconds(event)
        if event["period"] == previous_period:
            elapsed += max(0, clock - previous_clock) / speed
        # Period breaks are skipped; stoppage time within each period is preserved.
        previous_period, previous_clock = event["period"], clock
        while (remaining := origin + elapsed - time.monotonic()) > 0:
            if await disconnected():
                return
            await asyncio.sleep(min(remaining, 1))
            if remaining > 1:
                yield ": keep-alive\n\n"
        if await disconnected():
            return
        analytics = state.consume(event)
        # Deliberately omit raw fields (e.g. related_events linking future actions).
        payload = {
            "event": {
                key: event.get(key)
                for key in (
                    "id",
                    "index",
                    "period",
                    "timestamp",
                    "minute",
                    "second",
                    "type",
                    "team",
                    "player",
                    "location",
                    "possession",
                    "possession_team",
                )
            },
            "event_details": {
                kind: {key: event[kind][key] for key in fields if key in event[kind]}
                for kind, fields in {
                    "pass": ("recipient", "outcome", "type"),
                    "substitution": ("replacement",),
                    "bad_behaviour": ("card",),
                    "foul_committed": ("card",),
                }.items()
                if isinstance(event.get(kind), dict)
            },
            "end_location": next(
                (
                    event[key]["end_location"]
                    for key in ("pass", "carry", "shot")
                    if "end_location" in event.get(key, {})
                ),
                None,
            ),
            **analytics,
        }
        yield sse("update", payload, event["id"])
        # Resuming here means the frame was handed on, so the session may now use it.
        if session is not None:
            session.record(payload["event"], payload)
    yield sse("complete", {"match_id": match["match_id"]})


async def replay(
    events: list[dict],
    match: dict,
    speed: float,
    disconnected,
    provider: ExplanationProvider | None = None,
    audience: Audience = "casual",
    session: MatchSession | None = None,
):
    updates = replay_updates(events, match, speed, disconnected, session)
    if provider is None or provider.settings.explanation_provider == "off":
        async for frame in updates:
            yield frame
        return
    next_update = asyncio.create_task(anext(updates))
    pending = None
    calls = 0
    last_call = float("-inf")
    try:
        while next_update is not None or pending is not None:
            if await disconnected():
                return
            tasks = [task for task in (next_update, pending) if task is not None]
            done, _ = await asyncio.wait(tasks, timeout=0.5, return_when=asyncio.FIRST_COMPLETED)
            if pending is not None and pending in done:
                yield sse("insight", pending.result())
                pending = None
            if next_update is None or next_update not in done:
                continue
            try:
                frame = next_update.result()
            except StopAsyncIteration:
                next_update = None
                continue
            # Finish outstanding explanation before sending the completion marker.
            if "event: complete\n" in frame:
                next_update = None
                continue
            yield frame
            if "event: update\n" in frame:
                payload = json.loads(
                    next(line[6:] for line in frame.splitlines() if line.startswith("data: "))
                )
                if (
                    payload["shot_added"] is not None
                    and pending is None
                    and calls < provider.settings.explanation_max_calls
                    and time.monotonic() - last_call
                    >= provider.settings.explanation_interval_seconds
                ):
                    snapshot = deepcopy(payload)
                    # Position snapshots are for rendering; keep narrative context compact.
                    snapshot["shot_added"].pop("freeze_frame", None)
                    snapshot["shot_added"].pop("end_location", None)
                    snapshot["teams"] = [match["home_team"], match["away_team"]]
                    pending = asyncio.create_task(provider.explain(snapshot, audience))
                    calls += 1
                    last_call = time.monotonic()
            next_update = asyncio.create_task(anext(updates))
        yield sse("complete", {"match_id": match["match_id"]})
    finally:
        tasks = [task for task in (next_update, pending) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await updates.aclose()
