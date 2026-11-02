"""Render documentation charts (PNG) from docs/data/*.json: python -m tools.charts."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # Headless: no display is needed in CI or containers.
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"
IMAGES = ROOT / "docs" / "images"
ORIGINAL, ADDED = "#9aa5b1", "#1f6feb"


def tests_per_phase(phases: list[dict], baseline: int, path: Path) -> Path:
    """Stacked bars: Hadi's original tests plus tests added by Touchline+ phases."""
    labels = [f"P{p['phase']}\n{p['name']}" for p in phases]
    totals = [p["tests"] for p in phases]
    original = [min(baseline, total) for total in totals]
    added = [total - base for total, base in zip(totals, original, strict=True)]
    figure, axis = plt.subplots(figsize=(max(5, 1.1 * len(phases) + 2), 4), dpi=150)
    axis.bar(labels, original, width=0.6, color=ORIGINAL, label="Original Touchline tests")
    axis.bar(labels, added, width=0.6, bottom=original, color=ADDED, label="Added by Touchline+")
    for index, total in enumerate(totals):
        axis.text(index, total + max(totals) * 0.01, str(total), ha="center", va="bottom")
    axis.set_ylabel("Passing tests")
    axis.set_title("Passing tests after each phase")
    axis.set_ylim(0, max(totals) * 1.15)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2)
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path)
    plt.close(figure)
    return path


def bars(title: str, values: dict[str, float], ylabel: str, path: Path) -> Path:
    """A simple labelled bar chart for one measurable phase result."""
    figure, axis = plt.subplots(figsize=(max(5, 0.9 * len(values) + 2), 3.4), dpi=150)
    axis.bar(list(values), list(values.values()), color=ADDED)
    for index, value in enumerate(values.values()):
        axis.text(index, value, f"{value:g}", ha="center", va="bottom")
    axis.set_title(title)
    axis.set_ylabel(ylabel)
    axis.spines[["top", "right"]].set_visible(False)
    plt.setp(axis.get_xticklabels(), rotation=20, ha="right")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path)
    plt.close(figure)
    return path


def main() -> None:
    data = json.loads((DATA / "phases.json").read_text())
    phases = data["phases"]
    tests_per_phase(phases, data["baseline_tests"], IMAGES / "tests-per-phase.png")
    for index in range(len(phases)):
        tests_per_phase(
            phases[: index + 1],
            data["baseline_tests"],
            IMAGES / f"phase-{phases[index]['phase']}-tests.png",
        )
    for chart in data.get("charts", []):
        bars(chart["title"], chart["values"], chart["ylabel"], IMAGES / chart["file"])


if __name__ == "__main__":
    main()
