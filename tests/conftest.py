"""Shared test helpers: instant replays on a virtual clock (no sleeping, no network)."""

import asyncio
from unittest import mock

from app.replay import replay_updates
from app.sessions import MatchSession
from app.synthetic import SyntheticSource


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
