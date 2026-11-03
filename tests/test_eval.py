import csv
import json

import pytest

from app.agent.offline import OfflineAnalyst
from eval.agreement import agreement, cohen_kappa
from eval.run import HUMAN_FIELDS, fact_present, leaks
from eval.run import main as run_eval


def test_ci_subset_runs_offline_with_no_leakage(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_GEMINI_API_KEY", "")
    monkeypatch.setenv("GAME_OLLAMA_URL", "http://127.0.0.1:9")  # Never reachable.
    result = run_eval(["--subset", "ci", "--configs", "langgraph/offline", "--out", str(tmp_path)])
    offline = next(s for s in result["summary"] if s["config"] == "langgraph/offline")
    assert offline["questions"] == 5 and offline["errors"] == 0
    assert offline["leakage"] == 0 and offline["factual_accuracy"] >= 0.8
    assert all("skipped" in s for s in result["summary"] if s["config"] != "langgraph/offline")
    assert result["retrieval"]["hit_at_3"] == 1.0
    for name in ("results.json", "results.md", "results.png", "human_grading.csv"):
        assert (tmp_path / name).exists()
    with (tmp_path / "human_grading.csv").open() as file:
        rows = list(csv.DictReader(file))
    assert rows and list(rows[0]) == HUMAN_FIELDS and rows[0]["human_score"] == ""


def test_fact_matching_tolerates_rounding_but_not_wrong_numbers():
    assert fact_present("home.shots", 7, "Shots 7-6 so far")
    assert fact_present("away.shots", 6, "Shots 7-6 so far")
    assert fact_present("home.xg", 0.452, "xG 0.45 vs 0.10")
    assert not fact_present("home.xg", 0.452, "xG 0.48")
    assert fact_present("home.possession", 48.8, "about 49% of the ball")
    assert fact_present("score", "1-0", "It is Northbridge 1–0 Southbank")
    assert fact_present("momentum.leader", "Southbank United", "Southbank United are on top")


def test_leakage_detects_unemitted_citations_and_future_minutes():
    answer = {"text": "A goal in the 80th minute.", "cited_event_ids": ["future"]}
    problems = leaks(answer, {"past"}, (1, 0), 30)
    assert "unemitted:future" in problems and "future_minute" in problems
    assert leaks({"text": "It is 1-0.", "cited_event_ids": ["past"]}, {"past"}, (1, 0), 30) == []


def test_cohen_kappa_matches_known_values():
    assert cohen_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0
    # 2x2 example: observed agreement 0.7, chance agreement 0.54 → kappa = 0.16 / 0.46.
    a = [1] * 5 + [1] * 2 + [2] * 1 + [2] * 2
    b = [1] * 5 + [2] * 2 + [1] * 1 + [2] * 2
    assert cohen_kappa(a, b) == pytest.approx(0.3478, abs=1e-3)
    assert cohen_kappa([5, 4, 3], [4, 3, 2], "quadratic") > cohen_kappa([5, 4, 3], [4, 3, 2])
    assert cohen_kappa([], []) is None


def test_agreement_report_lists_disagreements():
    rows = [
        {"item": "h1", "config": "c", "question": "q", "judge_score": "5", "human_score": "5"},
        {"item": "h2", "config": "c", "question": "q", "judge_score": "4", "human_score": "2"},
        {"item": "h3", "config": "c", "question": "q", "judge_score": "3", "human_score": ""},
    ]
    report = agreement(rows)
    assert report["graded"] == 2 and report["exact_match_rate"] == 0.5
    assert report["within_1_rate"] == 0.5
    assert [d["item"] for d in report["disagreements"]] == ["h2"]
    assert agreement(rows[2:])["graded"] == 0


def test_offline_baseline_is_labelled_and_deterministic():
    model = OfflineAnalyst()
    assert model._llm_type == "offline-rule-based"
    assert json.dumps(model.model_dump()) == json.dumps(OfflineAnalyst().model_dump())
