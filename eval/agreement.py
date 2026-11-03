"""Judge–human agreement: python -m eval.agreement [eval/human_grading.csv].

Fill the `human_score` column (1–5, using eval/rubric.md) first. Reports exact-match rate,
within-1 rate, Cohen's kappa (unweighted and quadratic-weighted) and lists disagreements.
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

LABELS = (1, 2, 3, 4, 5)


def cohen_kappa(a: list[int], b: list[int], weights: str | None = None) -> float | None:
    """Cohen's kappa for two raters on the 1–5 scale; `weights="quadratic"` for weighted."""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    k = len(LABELS)
    index = {label: i for i, label in enumerate(LABELS)}

    def weight(i, j):
        if weights == "quadratic":
            return ((i - j) ** 2) / ((k - 1) ** 2)
        return 0.0 if i == j else 1.0

    observed = Counter((index[x], index[y]) for x, y in zip(a, b, strict=True))
    rows, cols = Counter(index[x] for x in a), Counter(index[y] for y in b)
    disagreement_observed = sum(weight(i, j) * c for (i, j), c in observed.items()) / n
    disagreement_expected = sum(
        weight(i, j) * rows[i] * cols[j] for i in range(k) for j in range(k)
    ) / (n * n)
    if disagreement_expected == 0:
        return 1.0 if disagreement_observed == 0 else 0.0
    return round(1 - disagreement_observed / disagreement_expected, 4)


def agreement(rows: list[dict]) -> dict:
    graded = [
        r for r in rows if str(r.get("human_score", "")).strip() and str(r.get("judge_score", ""))
    ]
    judge = [int(float(r["judge_score"])) for r in graded]
    human = [int(float(r["human_score"])) for r in graded]
    if not graded:
        return {"graded": 0, "note": "No human scores yet: fill human_score in the CSV."}
    exact = sum(j == h for j, h in zip(judge, human, strict=True))
    within = sum(abs(j - h) <= 1 for j, h in zip(judge, human, strict=True))
    return {
        "graded": len(graded),
        "exact_match_rate": round(exact / len(graded), 4),
        "within_1_rate": round(within / len(graded), 4),
        "cohen_kappa": cohen_kappa(judge, human),
        "quadratic_weighted_kappa": cohen_kappa(judge, human, "quadratic"),
        "disagreements": [
            {
                "item": r["item"],
                "config": r["config"],
                "question": r["question"],
                "judge": j,
                "human": h,
                "judge_justification": r.get("judge_justification"),
                "human_notes": r.get("human_notes"),
            }
            for r, j, h in zip(graded, judge, human, strict=True)
            if j != h
        ],
    }


def main(argv=None) -> dict:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else Path(__file__).with_name("human_grading.csv")
    with path.open(newline="", encoding="utf-8") as file:
        result = agreement(list(csv.DictReader(file)))
    path.with_name("agreement.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
