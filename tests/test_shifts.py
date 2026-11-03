import json

from conftest import synthetic_session

from app.agent.tools import MatchTools
from app.shifts import ShiftDetector, ShiftSettings

MATCH = {"home_team": {"id": 1, "name": "Home"}, "away_team": {"id": 2, "name": "Away"}}


def update(index, seconds, team, xt, possession=None, period=1):
    minute, second = divmod(int(seconds), 60)
    return {
        "event": {
            "id": f"e{index}",
            "period": period,
            "timestamp": f"00:{minute:02}:{second:02}.000",
            "minute": minute + (45 if period == 2 else 0),
            "second": second,
            "type": {"name": "Pass"},
            "team": {"id": team},
            "player": {"name": f"P{team}"},
            "possession": possession if possession is not None else index,
            "location": [50, 40],
        },
        "end_location": [70, 40],
        "momentum": {"action_value": xt},
    }


def spell(detector, start, end, team, xt=0.02, step=10, offset=0):
    found = []
    for index, seconds in enumerate(range(start, end, step)):
        if (shift := detector.consume(update(offset + index, seconds, team, xt))) is not None:
            found.append(shift)
    return found


def stream():
    session, frames = synthetic_session()
    parsed = []
    for frame in frames:
        kind = next((line[7:] for line in frame.splitlines() if line.startswith("event: ")), None)
        if kind:
            parsed.append((kind, json.loads(frame.split("data: ", 1)[1].split("\n")[0])))
    return session, parsed


def test_synthetic_match_produces_shifts_with_the_documented_shape():
    session, parsed = stream()
    shifts = [data for kind, data in parsed if kind == "momentum_shift"]
    assert len(shifts) >= 1
    for shift in shifts:
        assert {
            "minute",
            "period",
            "from_team",
            "to_team",
            "magnitude",
            "sequences",
            "players",
            "narration",
            "cited_event_ids",
        } <= set(shift)
        assert shift["magnitude"] >= 0.03
        assert shift["sequences"] and all(isinstance(seq, list) for seq in shift["sequences"])
        assert set(shift["cited_event_ids"]) <= {i for seq in shift["sequences"] for i in seq}
        assert shift["to_team"]["name"] in shift["narration"]
    assert [s["id"] for s in session.shifts] == [s["id"] for s in shifts]


def test_shift_never_references_events_after_it():
    _, parsed = stream()
    emitted = set()
    for kind, data in parsed:
        if kind == "update":
            emitted.add(data["event"]["id"])
        if kind == "momentum_shift":
            referenced = {i for seq in data["sequences"] for i in seq} | set(
                data["cited_event_ids"]
            )
            assert referenced <= emitted  # Only events already sent to the viewer.
            for chain in data["chain"]:
                for event in chain:
                    assert (event["period"], event["minute"]) <= (data["period"], data["minute"])


def test_shifts_need_the_gap_to_hold_for_three_minutes():
    detector = ShiftDetector(MATCH)
    assert spell(detector, 0, 170, team=1) == []  # Under three minutes of dominance.
    found = spell(detector, 170, 400, team=1, offset=100)
    assert len(found) == 1 and found[0]["to_team"]["id"] == 1 and found[0]["from_team"] is None


def test_debounce_keeps_shifts_five_minutes_apart():
    detector = ShiftDetector(MATCH, ShiftSettings(hold_seconds=60, window_seconds=60))
    first = spell(detector, 0, 200, team=1)
    second = spell(detector, 200, 330, team=2, offset=100)
    later = spell(detector, 330, 900, team=2, offset=200)
    assert len(first) == 1 and second == [] and len(later) == 1
    gap = (later[0]["minute"] * 60 + later[0]["second"]) - (
        first[0]["minute"] * 60 + first[0]["second"]
    )
    assert gap >= 300 and later[0]["from_team"]["id"] == 1


def test_detector_resets_each_period():
    detector = ShiftDetector(MATCH)
    spell(detector, 0, 400, team=1)
    assert detector.leader == 1
    detector.consume(update(999, 0, 2, 0.0, period=2))
    assert detector.leader is None and detector.candidate is None


def test_shifts_reach_session_snapshot_and_momentum_tool():
    session, _ = stream()
    assert session.snapshot()["momentum_shifts"]
    recent = MatchTools(session.view()).get_momentum(10)["recent_shifts"]
    assert recent and recent[-1]["id"] == session.shifts[-1]["id"]
    assert set(recent[-1]["cited_event_ids"]) <= session.view().event_ids()
