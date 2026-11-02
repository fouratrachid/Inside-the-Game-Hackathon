"""Explainable momentum shifts, detected causally from emitted events only.

A shift is declared when the team leading a rolling window of xT added changes, and the new
gap stays at or above a threshold for a hold period. Shifts are debounced and explained by the
top xT actions in the window, grouped into possession sequences with the players involved.
"""

from collections import deque
from dataclasses import dataclass

from app.analytics import period_seconds


@dataclass(frozen=True)
class ShiftSettings:
    threshold: float = 0.03  # Minimum gap in rolling positive xT added between teams.
    window_seconds: float = 300  # Rolling window for xT added.
    hold_seconds: float = 180  # The new gap must hold this long (≥3 match minutes).
    debounce_seconds: float = 300  # Shifts are at least five match minutes apart.
    top_actions: int = 3
    max_sequence: int = 8


def _clock_seconds(event: dict) -> float:
    try:
        return period_seconds(event)
    except KeyError, ValueError, AttributeError:
        return float((event.get("minute") or 0) * 60 + (event.get("second") or 0))


class ShiftDetector:
    """Feed it emitted update payloads in order; it returns a shift dict when one is confirmed."""

    def __init__(self, match: dict, settings: ShiftSettings | None = None):
        self.settings = settings or ShiftSettings()
        self.teams = {
            match["home_team"]["id"]: match["home_team"],
            match["away_team"]["id"]: match["away_team"],
        }
        self.home, self.away = match["home_team"]["id"], match["away_team"]["id"]
        self.count = 0
        self.last_shift_at: float | None = None
        self._reset_period(None)

    def _reset_period(self, period) -> None:
        self.period = period
        self.leader = None
        self.candidate: tuple | None = None  # (team_id, since_seconds, since_event)
        self.buffer: deque = deque()  # Emitted records within the explanation horizon.

    def _record(self, update: dict, seconds: float) -> dict:
        event = update["event"]
        momentum = update.get("momentum") or {}
        return {
            "id": event.get("id"),
            "seconds": seconds,
            "minute": event.get("minute"),
            "second": event.get("second"),
            "period": event.get("period"),
            "team_id": (event.get("team") or {}).get("id"),
            "type": (event.get("type") or {}).get("name"),
            "player": (event.get("player") or {}).get("name"),
            "possession": event.get("possession"),
            "location": event.get("location"),
            "end_location": update.get("end_location"),
            "xt": momentum.get("action_value"),
        }

    def window_xt(self, now: float) -> dict:
        start = now - self.settings.window_seconds
        totals = {self.home: 0.0, self.away: 0.0}
        for record in self.buffer:
            if record["seconds"] >= start and record["team_id"] in totals and record["xt"]:
                totals[record["team_id"]] += max(0.0, record["xt"])
        return totals

    def consume(self, update: dict) -> dict | None:
        event = update["event"]
        period = event.get("period")
        if period == 5:
            return None
        if period != self.period:
            self._reset_period(period)
        seconds = _clock_seconds(event)
        record = self._record(update, seconds)
        self.buffer.append(record)
        horizon = seconds - self.settings.window_seconds - self.settings.hold_seconds - 60
        while self.buffer and self.buffer[0]["seconds"] < horizon:
            self.buffer.popleft()
        totals = self.window_xt(seconds)
        gap = totals[self.home] - totals[self.away]
        side = None
        if abs(gap) >= self.settings.threshold:
            side = self.home if gap > 0 else self.away
        if side is None or side == self.leader:
            self.candidate = None
            return None
        if self.candidate is None or self.candidate[0] != side:
            self.candidate = (side, seconds, record)
            return None
        absolute = (period - 1) * 10_000 + seconds  # Monotonic across periods.
        held = seconds - self.candidate[1] >= self.settings.hold_seconds
        rested = (
            self.last_shift_at is None
            or absolute - self.last_shift_at >= self.settings.debounce_seconds
        )
        if not (held and rested):
            return None
        shift = self._explain(side, totals, gap, record)
        self.leader, self.candidate, self.last_shift_at = side, None, absolute
        return shift

    def _explain(self, to_team, totals: dict, gap: float, trigger: dict) -> dict:
        settings = self.settings
        since = self.candidate[2]
        start = trigger["seconds"] - settings.window_seconds
        window = [r for r in self.buffer if r["seconds"] >= start]
        top = sorted(
            (r for r in window if r["team_id"] == to_team and (r["xt"] or 0) > 0),
            key=lambda r: r["xt"],
            reverse=True,
        )[: settings.top_actions]
        sequences, chain, players = [], [], []
        for possession in dict.fromkeys(r["possession"] for r in top):
            last = max(
                (r for r in top if r["possession"] == possession), key=lambda r: r["seconds"]
            )
            steps = [
                r
                for r in self.buffer
                if r["possession"] == possession
                and r["team_id"] == to_team
                and r["seconds"] <= last["seconds"]
            ][-settings.max_sequence :]
            sequences.append([r["id"] for r in steps])
            chain.append(
                [
                    {
                        key: r[key]
                        for key in (
                            "id",
                            "minute",
                            "second",
                            "period",
                            "team_id",
                            "type",
                            "player",
                            "location",
                            "end_location",
                            "xt",
                        )
                    }
                    for r in steps
                ]
            )
            players.extend(r["player"] for r in steps if r["player"])
        self.count += 1
        from_team = self.teams.get(self.leader)
        team = self.teams[to_team]
        other = self.away if to_team == self.home else self.home
        top_xt = sum(r["xt"] for r in top)
        names = list(dict.fromkeys(players))
        lead = ", ".join(names[:2]) if names else "their build-up"
        narration = (
            f"{team['name']} took over from {since['minute']}′: "
            f"{len(top)} attacking actions involving {lead} added {top_xt:.2f} xT, "
            f"and {team['name']} lead the last {round(settings.window_seconds / 60)} minutes "
            f"{totals[to_team]:.2f} to {totals[other]:.2f} in xT added."
        )
        return {
            "id": f"shift-{self.count}",
            "minute": trigger["minute"],
            "second": trigger["second"],
            "period": trigger["period"],
            "since_minute": since["minute"],
            "trigger_event_id": trigger["id"],
            "from_team": {"id": from_team["id"], "name": from_team["name"]} if from_team else None,
            "to_team": {"id": team["id"], "name": team["name"]},
            "magnitude": round(abs(gap), 4),
            "window_xt": {str(k): round(v, 4) for k, v in totals.items()},
            "top_actions": [
                {"event_id": r["id"], "xt": round(r["xt"], 4), "player": r["player"]} for r in top
            ],
            "sequences": sequences,
            "chain": chain,
            "players": names,
            "narration": narration,
            "cited_event_ids": [r["id"] for r in top],
        }
