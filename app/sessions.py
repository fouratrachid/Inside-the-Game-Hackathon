"""Server-side match sessions: the only source of match context for chat.

Each `/matches/{id}/stream` connection owns one `MatchSession`. The replay calls
`record()` only after an update frame has been yielded to the client, so the session never
knows more than the viewer has seen, and browsers can no longer inject match context.
"""

import secrets
import time
from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field

from app.analytics import MinuteHistory, PlayerAccumulator
from app.usage import SessionUsage

RECENT_EVENTS = 60
SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{16,64}$"


def summarize(event: dict, analytics: dict) -> dict:
    """Compact event summary matching the UI's event timeline (newest-first excerpt)."""
    details = analytics.get("event_details") or {}
    kind = (event.get("type") or {}).get("name") or "Event"
    team = event.get("team") or {}
    action = kind
    if kind == "Shot":
        outcome = (analytics.get("shot_added") or {}).get("outcome")
        action = f"Shot · {outcome or 'Outcome unavailable'}"
    if kind == "Pass":
        details_pass = details.get("pass") or {}
        corner = (details_pass.get("type") or {}).get("name") == "Corner"
        outcome = (details_pass.get("outcome") or {}).get("name") or "Completed"
        action = f"{'Corner' if corner else 'Pass'} · {outcome}"
    card = (details.get("bad_behaviour") or {}).get("card") or (
        details.get("foul_committed") or {}
    ).get("card")
    if (card or {}).get("name"):
        action += f" · {card['name']}"
    return {
        "id": event.get("id"),
        "minute": event.get("minute"),
        "second": event.get("second"),
        "period": event.get("period"),
        "team": team.get("name") or "Match",
        "team_id": team.get("id"),
        "action": action,
        "player": (event.get("player") or {}).get("name"),
    }


def compact(event: dict, analytics: dict) -> dict:
    """Per-event record kept for the whole replay (Phase 2); heavy analytics are not."""
    momentum = analytics.get("momentum") or {}
    return {
        "event": event,
        "details": analytics.get("event_details") or {},
        "end_location": analytics.get("end_location"),
        "shot": analytics.get("shot_added"),
        "xt": momentum.get("action_value"),
        "momentum": {k: momentum.get(k) for k in ("home", "away", "net_difference")},
        "summary": summarize(event, analytics),
    }


@dataclass(frozen=True)
class SessionView:
    """Immutable view of a session at one instant, used by the agent's tools."""

    id: str
    match: dict
    clock: dict | None
    latest: dict | None
    history: tuple
    players: dict
    minutes: list
    snapshot: dict | None
    shifts: tuple = ()

    def event_ids(self) -> set:
        return {record["event"].get("id") for record in self.history}


@dataclass
class MatchSession:
    match: dict
    id: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    latest: dict | None = None
    clock: dict | None = None
    events: deque = field(default_factory=lambda: deque(maxlen=RECENT_EVENTS))
    seen: set = field(default_factory=set)
    touched: float = field(default_factory=lambda: time.monotonic())
    history: list = field(default_factory=list)
    players: PlayerAccumulator = field(default_factory=PlayerAccumulator)
    minutes: MinuteHistory = field(default_factory=MinuteHistory)
    shifts: list = field(default_factory=list)
    usage: SessionUsage = field(default_factory=SessionUsage)

    def record(self, event: dict, analytics: dict) -> bool:
        """Record an emitted update. Call only after its frame was yielded. Idempotent."""
        identifier = event.get("id")
        if identifier in self.seen:
            return False
        self.seen.add(identifier)
        self.events.appendleft(summarize(event, analytics))
        self.history.append(compact(event, analytics))
        update = {**analytics, "event": event}
        self.players.consume(update)
        self.minutes.consume(update)
        self.latest = analytics
        self.clock = {
            "minute": event.get("minute"),
            "second": event.get("second"),
            "period": event.get("period"),
        }
        self.touched = time.monotonic()
        return True

    def record_shift(self, shift: dict) -> None:
        """Store a momentum shift after its SSE frame was yielded."""
        if all(existing["id"] != shift["id"] for existing in self.shifts):
            self.shifts.append(shift)

    def snapshot(self) -> dict | None:
        """The chat context: latest stats plus the last 60 emitted events, newest first."""
        if self.latest is None:
            return None
        latest = self.latest
        return deepcopy(
            {
                "match": {
                    "home_team": self.match["home_team"],
                    "away_team": self.match["away_team"],
                },
                "clock": self.clock,
                "score": latest.get("score"),
                "stats": latest.get("match_stats"),
                "shot_summary": latest.get("shot_summary"),
                "possession": latest.get("possession"),
                "momentum": latest.get("momentum"),
                "passing_network": latest.get("passing_network"),
                "events": list(self.events),
                "momentum_shifts": [
                    {k: v for k, v in shift.items() if k != "chain"} for shift in self.shifts[-3:]
                ],
            }
        )

    def view(self) -> SessionView:
        """Freeze the session now; later replay events cannot leak into an answer."""
        return SessionView(
            id=self.id,
            match=self.match,
            clock=dict(self.clock) if self.clock else None,
            latest=self.latest,
            history=tuple(self.history),
            players=self.players.snapshot(),
            minutes=self.minutes.snapshot(),
            snapshot=self.snapshot(),
            shifts=tuple(self.shifts),
        )


class SessionStore:
    """In-memory sessions with a TTL and a capacity; the least recently used are evicted."""

    def __init__(self, max_sessions: int = 500, ttl_seconds: float = 3 * 3600):
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self._sessions: OrderedDict[str, MatchSession] = OrderedDict()

    def _expire(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        for key in [key for key, s in self._sessions.items() if s.touched < cutoff]:
            del self._sessions[key]

    def create(self, match: dict) -> MatchSession:
        self._expire()
        session = MatchSession(match)
        self._sessions[session.id] = session
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)
        return session

    def get(self, session_id: str) -> MatchSession | None:
        self._expire()
        session = self._sessions.get(session_id)
        if session is not None:
            session.touched = time.monotonic()
            self._sessions.move_to_end(session_id)
        return session

    def __len__(self) -> int:
        return len(self._sessions)
