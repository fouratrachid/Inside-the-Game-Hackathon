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


@dataclass
class MatchSession:
    match: dict
    id: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    latest: dict | None = None
    clock: dict | None = None
    events: deque = field(default_factory=lambda: deque(maxlen=RECENT_EVENTS))
    seen: set = field(default_factory=set)
    touched: float = field(default_factory=lambda: time.monotonic())

    def record(self, event: dict, analytics: dict) -> bool:
        """Record an emitted update. Call only after its frame was yielded. Idempotent."""
        identifier = event.get("id")
        if identifier in self.seen:
            return False
        self.seen.add(identifier)
        self.events.appendleft(summarize(event, analytics))
        self.latest = analytics
        self.clock = {
            "minute": event.get("minute"),
            "second": event.get("second"),
            "period": event.get("period"),
        }
        self.touched = time.monotonic()
        return True

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
            }
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
