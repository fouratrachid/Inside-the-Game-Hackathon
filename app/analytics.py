"""Incremental, deterministic event analytics in StatsBomb's 120 x 80 coordinates."""

from copy import deepcopy
from math import isfinite

from app.passing import PassingNetworks
from app.peak_momentum import PeakMomentum
from app.xt import MODEL_ID, action_xt


def shot_freeze_frame(shot: dict) -> list[dict]:
    """Keep recorded shot-time players; never infer missing positions."""
    players = []
    for entry in shot.get("freeze_frame") or []:
        location = entry.get("location")
        if not isinstance(location, list) or len(location) < 2:
            continue
        if not all(isinstance(v, (int, float)) and isfinite(v) for v in location[:2]):
            continue
        position = entry.get("position") or {}
        players.append(
            {
                "location": location[:2],
                "player": entry.get("player"),
                "position": position,
                "teammate": entry.get("teammate"),
                "goalkeeper": position.get("id") == 1 or position.get("name") == "Goalkeeper",
            }
        )
    return players


def period_seconds(event: dict) -> float:
    hours, minutes, seconds = event["timestamp"].split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


class MatchAnalytics:
    def __init__(self, home_id: int, away_id: int):
        self.team_ids = (home_id, away_id)
        self.peak_momentum = PeakMomentum(self.team_ids)
        self.period = None
        self.counts = {team: 0 for team in self.team_ids}
        self.last_time = None
        self.seen = set()
        self.shots = []
        self.score = {str(team): 0 for team in self.team_ids}
        self.possession_seconds = {team: 0.0 for team in self.team_ids}
        self.possession_previous = None
        self.passing_networks = PassingNetworks(self.team_ids)
        self.match_stats = {
            team: {
                "passes": 0,
                "completed_passes": 0,
                "shots_on_target": 0,
                "final_third_passes": 0,
                "corners": 0,
                "tackles": 0,
            }
            for team in self.team_ids
        }

    def consume(self, event: dict) -> dict:
        now = period_seconds(event)
        period = event["period"]
        if event["id"] not in self.seen:
            previous = self.possession_previous
            if previous is not None and previous[0] == period and period != 5:
                _, previous_time, owner = previous
                if owner in self.possession_seconds:
                    self.possession_seconds[owner] += max(0, now - previous_time)
            owner = (event.get("possession_team") or {}).get("id")
            # Do not count the wait for a restart after an explicit stoppage.
            if event.get("out") or event["type"]["name"] in {
                "Half End",
                "Injury Stoppage",
                "Referee Ball-Drop",
                "Foul Committed",
                "Offside",
            }:
                owner = None
            previous_time = previous[1] if previous and previous[0] == period else now
            self.possession_previous = (period, max(now, previous_time), owner)
        if self.period != period:
            self.counts = {team: 0 for team in self.team_ids}
            self.last_time = None
            self.period = period
        now = max(now, self.last_time if self.last_time is not None else now)
        self.last_time = now
        action_value = None
        added_shot = None
        if event["id"] not in self.seen:
            self.seen.add(event["id"])
            self.passing_networks.consume(event)
            team = event.get("team", {}).get("id")
            if team in self.team_ids and period != 5:
                self.consume_match_stats(event, team)
                if event["type"]["name"] == "Own Goal Against":
                    opponent = next(t for t in self.team_ids if t != team)
                    self.score[str(opponent)] += 1
                elif (
                    event["type"]["name"] == "Shot"
                    and event.get("shot", {}).get("outcome", {}).get("name") == "Goal"
                ):
                    self.score[str(team)] += 1
            if team in self.team_ids and period != 5:
                value = action_xt(event)
                if value is not None:
                    self.counts[team] += 1
                    action_value = value
            if event["type"]["name"] == "Shot" and team in self.team_ids:
                details = event["shot"]
                location = event.get("location")
                added_shot = {
                    "event_id": event["id"],
                    "team_id": team,
                    "player": event.get("player"),
                    "period": period,
                    "minute": event["minute"],
                    "second": event["second"],
                    "location": location,
                    "xg": details.get("statsbomb_xg"),
                    "outcome": details.get("outcome", {}).get("name"),
                    "body_part": details.get("body_part", {}).get("name"),
                    "shot_type": details.get("type", {}).get("name"),
                    "shootout": period == 5,
                    "freeze_frame": shot_freeze_frame(details),
                    "end_location": details.get("end_location"),
                }
                self.shots.append(added_shot)
        momentum = self.peak_momentum.consume(event, now)
        possession_total = sum(self.possession_seconds.values())
        final_third_total = sum(stats["final_third_passes"] for stats in self.match_stats.values())
        result = {
            "passing_network": self.passing_networks.snapshot(),
            "match_stats": {
                str(team): {
                    **stats,
                    "field_tilt": (
                        100 * stats["final_third_passes"] / final_third_total
                        if final_third_total
                        else None
                    ),
                    "pass_completion": (
                        100 * stats["completed_passes"] / stats["passes"]
                        if stats["passes"]
                        else None
                    ),
                }
                for team, stats in self.match_stats.items()
            },
            "possession": {
                "method": "event_time",
                "seconds": {str(team): value for team, value in self.possession_seconds.items()},
                "percentages": {
                    str(team): value / possession_total * 100 if possession_total else None
                    for team, value in self.possession_seconds.items()
                },
            },
            "score": dict(self.score),
            "momentum": {
                **momentum,
                "period": period,
                "period_seconds": now,
                "action_value": action_value,
                "model": MODEL_ID,
                "period_observations": {str(team): self.counts[team] for team in self.team_ids},
            },
            "shot_added": added_shot,
            "shot_summary": {
                str(team): {
                    "shots": sum(s["team_id"] == team and not s["shootout"] for s in self.shots),
                    "xg": round(
                        sum(
                            (s["xg"] or 0)
                            for s in self.shots
                            if s["team_id"] == team and not s["shootout"]
                        ),
                        4,
                    ),
                }
                for team in self.team_ids
            },
        }
        return deepcopy(result)

    def consume_match_stats(self, event: dict, team: int) -> None:
        stats = self.match_stats[team]
        kind = event["type"]["name"]
        if kind == "Pass":
            details = event.get("pass", {})
            stats["passes"] += 1
            stats["completed_passes"] += not details.get("outcome")
            stats["corners"] += details.get("type", {}).get("name") == "Corner"
        if kind == "Duel" and event.get("duel", {}).get("type", {}).get("name") == "Tackle":
            stats["tackles"] += 1
        if kind == "Shot":
            outcome = event.get("shot", {}).get("outcome", {}).get("name")
            stats["shots_on_target"] += outcome in {"Goal", "Saved", "Saved to Post"}
        if kind != "Pass" or event.get("pass", {}).get("outcome"):
            return
        location = event.get("location")
        if not isinstance(location, (list, tuple)) or len(location) < 2:
            return
        if any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v)
            for v in location[:2]
        ):
            return
        x, y = location[:2]
        # Both teams' raw StatsBomb coordinates face +x, including after halftime.
        stats["final_third_passes"] += 80 <= x <= 120 and 0 <= y <= 80


# Touchline+ accumulators -------------------------------------------------------------------
# These consume *emitted* update payloads (the dicts the replay yields), not raw events, so a
# MatchSession can feed them after each frame is sent and they can never see future events.

GOAL_CENTRE = (120.0, 40.0)
TOUCH_TYPES = {
    "Pass",
    "Carry",
    "Shot",
    "Dribble",
    "Ball Receipt*",
    "Ball Recovery",
    "Clearance",
    "Interception",
    "Miscontrol",
    "Dispossessed",
    "Block",
}


def _distance_to_goal(location) -> float | None:
    if not isinstance(location, (list, tuple)) or len(location) < 2:
        return None
    if not all(isinstance(v, (int, float)) and isfinite(v) for v in location[:2]):
        return None
    return ((GOAL_CENTRE[0] - location[0]) ** 2 + (GOAL_CENTRE[1] - location[1]) ** 2) ** 0.5


def is_progressive(start, end) -> bool:
    """A completed pass that moves the ball at least 25% closer to the goal centre."""
    before, after = _distance_to_goal(start), _distance_to_goal(end)
    return before is not None and after is not None and before > 0 and after <= 0.75 * before


def _update_parts(update: dict):
    event = update["event"]
    kind = (event.get("type") or {}).get("name")
    team = (event.get("team") or {}).get("id")
    details = update.get("event_details") or {}
    completed = kind == "Pass" and not (details.get("pass") or {}).get("outcome")
    shot = update.get("shot_added") if kind == "Shot" else None
    xt = (update.get("momentum") or {}).get("action_value")
    return event, kind, team, completed, shot, xt


class PlayerAccumulator:
    """Per-player match-to-date totals keyed by player id."""

    FIELDS = (
        "passes",
        "completed_passes",
        "progressive_passes",
        "shots",
        "goals",
        "xg",
        "xt_added",
        "touches",
    )

    def __init__(self):
        self.players: dict = {}

    def consume(self, update: dict) -> None:
        event, kind, team, completed, shot, xt = _update_parts(update)
        player = event.get("player") or {}
        key = player.get("id") or player.get("name")
        if key is None or event.get("period") == 5:
            return
        stats = self.players.setdefault(
            key,
            {
                "id": player.get("id"),
                "name": player.get("name"),
                "team_id": team,
                "team": (event.get("team") or {}).get("name"),
                **{field: 0 for field in self.FIELDS},
            },
        )
        stats["touches"] += kind in TOUCH_TYPES
        if kind == "Pass":
            stats["passes"] += 1
            stats["completed_passes"] += completed
            stats["progressive_passes"] += completed and is_progressive(
                event.get("location"), update.get("end_location")
            )
        if shot:
            stats["shots"] += 1
            stats["goals"] += shot.get("outcome") == "Goal"
            stats["xg"] = round(stats["xg"] + (shot.get("xg") or 0), 4)
        if xt is not None:
            stats["xt_added"] = round(stats["xt_added"] + xt, 4)

    def snapshot(self) -> dict:
        return {key: dict(value) for key, value in self.players.items()}


class MinuteHistory:
    """Per-minute team totals (shots, xG, xT, passes) so time windows can be compared."""

    FIELDS = ("shots", "xg", "xt", "passes", "completed_passes")

    def __init__(self):
        self.rows: dict[tuple[int, int, object], dict] = {}

    def consume(self, update: dict) -> None:
        event, kind, team, completed, shot, xt = _update_parts(update)
        if team is None or event.get("period") == 5:
            return
        key = (event.get("period"), event.get("minute"), team)
        row = self.rows.setdefault(key, {field: 0 for field in self.FIELDS})
        row["passes"] += kind == "Pass"
        row["completed_passes"] += completed
        if shot:
            row["shots"] += 1
            row["xg"] = round(row["xg"] + (shot.get("xg") or 0), 4)
        if xt is not None:
            row["xt"] = round(row["xt"] + xt, 4)

    def snapshot(self) -> list[dict]:
        return [
            {"period": period, "minute": minute, "team_id": team, **row}
            for (period, minute, team), row in sorted(
                self.rows.items(), key=lambda item: (item[0][0], item[0][1], str(item[0][2]))
            )
        ]


def window_totals(rows: list[dict], start_min: int, end_min: int) -> dict:
    """Sum minute rows per team inside [start_min, end_min) and outside it."""
    result: dict = {"inside": {}, "outside": {}}
    for row in rows:
        side = "inside" if start_min <= row["minute"] < end_min else "outside"
        totals = result[side].setdefault(
            str(row["team_id"]), {field: 0 for field in MinuteHistory.FIELDS}
        )
        for field in MinuteHistory.FIELDS:
            totals[field] = round(totals[field] + row[field], 4)
    return result
