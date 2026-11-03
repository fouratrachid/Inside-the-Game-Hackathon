"""Replay a match up to a stop minute instantly (no sleeping) into a MatchSession."""

import asyncio

from app.replay import replay_updates
from app.sessions import MatchSession
from app.synthetic import SyntheticSource


async def replay_to(source, match_id: int, stop_minute: int) -> MatchSession:
    """Emit every event before `stop_minute`, exactly as the live replay would, then stop."""
    match = next(m for m in await source.matches() if m["match_id"] == match_id)
    events = [e for e in await source.events(match_id) if e["minute"] < stop_minute]
    session = MatchSession(match)

    async def connected():
        return False

    # Speed 1e12: the pacing arithmetic yields (effectively) zero waiting time.
    async for _ in replay_updates(events, match, 1e12, connected, session):
        pass
    return session


def source_for(match_id: int):
    """Synthetic match 1 needs no network; other ids come from StatsBomb open data."""
    if match_id == 1:
        return SyntheticSource()
    from app.source import StatsBombSource

    return StatsBombSource()


def replay_sync(match_id: int, stop_minute: int) -> MatchSession:
    return asyncio.run(replay_to(source_for(match_id), match_id, stop_minute))
