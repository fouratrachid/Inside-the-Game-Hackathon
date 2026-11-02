"""Build eval/questions.json: questions, stop minutes and facts computed by the analytics.

Run: pipenv run python -m eval.build_questions
Facts come from the same Python analytics and tools the agent uses, at the stop minute.
"""

import json
from pathlib import Path

from app.agent.tools import MatchTools
from eval.replay import replay_sync

OUT = Path(__file__).with_name("questions.json")
MATCH_ID = 1  # The seeded synthetic match: deterministic and offline.
STOPS = (20, 44, 70, 89)
DEFINITIONS = [
    ("What is field tilt?", "knowledge/field-tilt.md"),
    ("What does xT mean?", "knowledge/xt.md"),
    ("What is xG?", "knowledge/xg.md"),
    ("How is possession estimated?", "knowledge/possession.md"),
    ("What is the momentum proxy?", "knowledge/momentum.md"),
    ("What does a passing network mean?", "knowledge/passing-networks.md"),
]


def facts_at(stop: int) -> list[dict]:
    session = replay_sync(MATCH_ID, stop)
    view = session.view()
    tools = MatchTools(view)
    stats = tools.get_match_stats()["teams"]
    (home_name, home), (away_name, away) = list(stats.items())
    players = sorted(view.players.values(), key=lambda p: (-p["passes"], p["name"]))
    passer = players[0]
    shooter = sorted(view.players.values(), key=lambda p: (-p["shots"], -p["xg"], p["name"]))[0]
    early = tools.compare_periods(0, 15)["inside"]
    momentum = tools.get_momentum(10)
    questions = [
        ("score", "What is the score?", {"score": f"{home['goals']}-{away['goals']}"}),
        (
            "shots",
            "How many shots does each team have?",
            {"home.shots": home["shots"], "away.shots": away["shots"]},
        ),
        (
            "chances",
            "Who has created the better chances so far?",
            {"home.xg": home["xg"], "away.xg": away["xg"]},
        ),
        (
            "possession",
            "How is possession split?",
            {"home.possession": home["possession_pct"], "away.possession": away["possession_pct"]},
        ),
        (
            "field_tilt",
            "What does field tilt say so far?",
            {"home.field_tilt": home["field_tilt_pct"], "away.field_tilt": away["field_tilt_pct"]},
        ),
        (
            "player_passes",
            f"How many passes has {passer['name']} made?",
            {"player.passes": passer["passes"], "player.completed": passer["completed_passes"]},
        ),
        (
            "player_shots",
            f"How many shots has {shooter['name']} taken, and for how much xG?",
            {"player.shots": shooter["shots"], "player.xg": shooter["xg"]},
        ),
        (
            "window",
            "Compare the first 15 minutes for both teams.",
            {
                "window.home.shots": early[home_name]["shots"],
                "window.away.shots": early[away_name]["shots"],
                "window.home.passes": early[home_name]["passes"],
            },
        ),
    ]
    if stop <= 44:
        questions.append(
            (
                "momentum",
                "Who is on top in the last 10 minutes?",
                {"momentum.leader": momentum["leading_team"] or "Neither"},
            )
        )
    return [
        {
            "id": f"m{MATCH_ID}-{stop}-{kind}",
            "kind": kind,
            "match_id": MATCH_ID,
            "stop_minute": stop,
            "question": question,
            "expected": facts,
        }
        for kind, question, facts in questions
    ]


def main() -> None:
    items = [item for stop in STOPS for item in facts_at(stop)][:30]
    items += [
        {
            "id": f"def-{index}",
            "kind": "definition",
            "match_id": MATCH_ID,
            "stop_minute": 30,
            "question": question,
            "expected": {"source": source},
        }
        for index, (question, source) in enumerate(DEFINITIONS, start=1)
    ]
    OUT.write_text(json.dumps(items, indent=2) + "\n")
    print(f"Wrote {len(items)} questions to {OUT}")


if __name__ == "__main__":
    main()
