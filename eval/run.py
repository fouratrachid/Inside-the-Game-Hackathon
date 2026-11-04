"""Run the evaluation: python -m eval.run [--subset ci] [--configs langgraph/offline,...].

For every question: replay the match to the stop minute (no sleeping), ask each configured
pipeline, and score factual accuracy, citation validity, leakage, latency and tool calls.
A judge model grades answers 1–5 against eval/rubric.md (a heuristic stands in when no
model is configured). Writes eval/results.json, eval/results.md, eval/results.png and,
if absent, eval/human_grading.csv.
"""

import argparse
import asyncio
import json
import re
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import HTTPException

from app.agent.llm import build_model
from app.agent.service import MatchAgent
from app.chat import ChatRequest, MatchChat
from app.config import Settings
from app.guardrails import check_output
from app.rag.embeddings import build_embedder
from app.rag.ingest import ingest
from app.rag.knowledge import KnowledgeBase
from app.rag.store import ChromaStore
from app.usage import DEFAULT_PRICES, cost_usd
from eval.replay import replay_to, source_for

HERE = Path(__file__).resolve().parent
CI_SUBSET = ["m1-20-score", "m1-20-shots", "m1-44-possession", "m1-44-player_passes", "def-1"]


@dataclass
class Config:
    name: str  # e.g. "langgraph/gemini"
    agent: str
    provider: str
    available: bool
    reason: str = ""


def ollama_up(settings: Settings) -> bool:
    try:
        return httpx.get(settings.ollama_url.rstrip("/") + "/api/tags", timeout=1).is_success
    except httpx.HTTPError:
        return False


def discover(base: Settings) -> list[Config]:
    gemini = bool(base.gemini_api_key.get_secret_value())
    foundry = bool(base.foundry_api_key.get_secret_value() and base.foundry_endpoint)
    ollama = ollama_up(base)
    configs = [Config("langgraph/offline", "langgraph", "offline", True)]
    for agent in ("langgraph", "maf"):
        configs.append(Config(f"{agent}/gemini", agent, "gemini", gemini, "no GAME_GEMINI_API_KEY"))
        configs.append(
            Config(f"{agent}/foundry", agent, "foundry", foundry, "no Foundry credentials")
        )
    configs.append(
        Config("langgraph/ollama", "langgraph", "ollama", ollama, "Ollama not reachable")
    )
    return configs


# Unsigned: "7-6" is two counts, not 7 and -6. No expected fact is negative.
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def fact_present(key: str, value, text: str) -> bool:
    """Is an expected fact stated in the answer (allowing sensible rounding)?"""
    if isinstance(value, str):
        if key == "score":
            home, away = value.split("-")
            return bool(re.search(rf"\b{home}\s*[-–]\s*{away}\b", text))
        return value.lower() in text.lower()
    if value is None:
        return bool(re.search(r"unknown|not available|no data|don't have", text, re.I))
    numbers = [float(n) for n in NUMBER.findall(text)]
    if isinstance(value, int):
        return any(n == value for n in numbers)
    tolerance = 0.6 if "possession" in key or "tilt" in key else 0.006
    return any(abs(n - value) <= tolerance for n in numbers)


def leaks(answer: dict, emitted: set, score: tuple, stop_minute: int) -> list[str]:
    problems = [f"unemitted:{i}" for i in answer.get("cited_event_ids", []) if i not in emitted]
    problems += [
        p
        for p in check_output(
            answer.get("text", ""),
            score=score,
            clock_minute=stop_minute,
            secrets=[],
            system_prompt="",
        )
        if p in {"score_mismatch", "future_minute"}
    ]
    return problems


class HeuristicJudge:
    """Stand-in when no judge model is configured. Clearly labelled; not an LLM."""

    name = "heuristic (no judge model configured)"

    async def grade(self, item, answer, metrics) -> tuple[int, str]:
        if answer.get("error"):
            return None, f"Not judged (no answer): {answer['error']}"
        quality = 0.6 * metrics["fact_accuracy"] + 0.2 * metrics["citation_ok"]
        quality += 0.2 * (0 if metrics["leaks"] else 1)
        score = max(1, min(5, 1 + round(4 * quality)))
        return score, (
            f"{metrics['facts_matched']}/{metrics['facts_total']} expected facts stated; "
            f"{'no' if not metrics['leaks'] else 'has'} leakage."
        )


class LLMJudge:
    def __init__(self, model, name: str):
        self.model = model
        self.name = name
        self.rubric = (HERE / "rubric.md").read_text()

    async def grade(self, item, answer, metrics) -> tuple[int | None, str]:
        if answer.get("error"):
            return None, f"Not judged (no answer): {answer['error']}"
        prompt = (
            f"{self.rubric}\n\nQuestion (replay stopped at minute {item['stop_minute']}): "
            f"{item['question']}\nExpected facts: {json.dumps(item['expected'])}\n"
            f"Tools used: {json.dumps(answer.get('tools_used', []))}\n"
            f"Answer: {answer.get('text', '')}\n\n"
            'Reply with only JSON: {"score": <1-5>, "justification": "<one or two sentences>"}'
        )
        try:
            reply = await self.model.ainvoke(prompt)
            text = reply.content if isinstance(reply.content, str) else str(reply.content)
            data = json.loads(text[text.find("{") : text.rfind("}") + 1])
            return max(1, min(5, int(data["score"]))), str(data["justification"])[:300]
        except Exception as error:  # A failed judgement is recorded, not fatal.
            return None, f"Judge failed: {type(error).__name__}"


def pick_judge(config: Config, configs: list[Config], base: Settings, judge_model=None):
    """Prefer a different provider from the one being graded; never the offline baseline.

    With only one provider available, `judge_model` lets a different model of that provider
    judge (e.g. grade gemini-3.8-flash answers with gemini-3.5-flash).
    """
    if judge_model and config.provider == "gemini" and base.gemini_api_key.get_secret_value():
        settings = base.model_copy(update={"chat_provider": "gemini", "gemini_model": judge_model})
        return LLMJudge(build_model(settings), f"gemini judge ({judge_model})")
    candidates = [c for c in configs if c.available and c.provider != "offline"]
    other = [c for c in candidates if c.provider != config.provider] or candidates
    if not other:
        return HeuristicJudge()
    chosen = other[0]
    settings = base.model_copy(update={"chat_provider": chosen.provider})
    return LLMJudge(build_model(settings), f"{chosen.provider} judge")


def knowledge(base: Settings, folder: Path):
    store = ChromaStore(folder, "eval")
    embedder = build_embedder(base)
    ingest(store, embedder)
    return KnowledgeBase(store, embedder, base.rag_top_k)


class MeteredMatchChat(MatchChat):
    """The original workflow, unchanged, but recording the token usage Gemini reports."""

    def __init__(self, settings, usage: list):
        super().__init__(settings)
        self.usage = usage

    async def _generate(self, payload, key):
        response = await super()._generate(payload, key)
        try:
            data = response.json()
        except ValueError:
            return response
        if isinstance(data, dict) and isinstance(data.get("usage"), dict):
            self.usage.append(data["usage"])  # Interactions API usage block.
        return response


RETRYABLE = ("429", "503", "502", "504")


async def ask_once(config: Config, settings: Settings, session, item, kb) -> dict:
    started = time.perf_counter()
    try:
        if config.agent == "langgraph":
            agent = MatchAgent(settings, knowledge=kb)
            answer = await agent.ask(item["question"], "analyst", session)
        else:
            usage: list = []
            request = ChatRequest(
                question=item["question"], mode="analyst", snapshot=session.snapshot()
            )
            answer = await MeteredMatchChat(settings, usage).ask(request)
            answer["tools_used"] = [{"tool": t, "args": {}} for t in answer.get("tools_used", [])]
            answer["cited_event_ids"] = answer.get("evidence_event_ids", [])
            input_tokens = sum(u.get("total_input_tokens", 0) for u in usage)
            # Thinking tokens are billed as output.
            output_tokens = sum(
                u.get("total_output_tokens", 0) + u.get("total_thought_tokens", 0) for u in usage
            )
            answer["usage"] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "model_calls": len(usage),
            }
    except HTTPException as error:
        answer = {"error": f"{error.status_code}: {error.detail}"}
    answer["latency_s"] = round(time.perf_counter() - started, 4)
    return answer


async def ask(config, base, session, item, kb, retries: int = 0, backoff: float = 20) -> dict:
    """Ask once; on quota/overload errors wait and retry. Latency is the final attempt's."""
    settings = base.model_copy(
        update={
            "chat_provider": config.provider,
            "agent": config.agent,
            "trace_log": "",
            "session_budget_usd": 0,  # Evaluation must not be cut off by the per-replay budget.
        }
    )
    attempts = 0
    while True:
        answer = await ask_once(config, settings, session, item, kb)
        attempts += 1
        error = answer.get("error") or ""
        if not error.startswith(RETRYABLE) or attempts > retries:
            answer["attempts"] = attempts
            return answer
        await asyncio.sleep(backoff * attempts)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[index], 4)


async def run(
    items: list[dict],
    configs: list[Config],
    base: Settings,
    kb,
    *,
    judge_model: str | None = None,
    pause: float = 0,
    retries: int = 0,
) -> dict:
    prices = {**DEFAULT_PRICES, **base.model_prices}
    sessions = {}
    rows = []
    for item in items:
        key = (item["match_id"], item["stop_minute"])
        if key not in sessions:
            sessions[key] = await replay_to(source_for(key[0]), *key)
    for config in [c for c in configs if c.available]:
        judge = pick_judge(config, configs, base, judge_model)
        for index, item in enumerate(items):
            if pause and index:
                await asyncio.sleep(pause)  # Stay under free-tier requests-per-minute limits.
            session = sessions[(item["match_id"], item["stop_minute"])]
            view = session.view()
            answer = await ask(config, base, session, item, kb, retries)
            usage = answer.get("usage") or {}
            model = base.gemini_model if config.provider == "gemini" else config.provider
            cost = cost_usd(
                model, usage.get("input_tokens", 0), usage.get("output_tokens", 0), prices
            )
            text = answer.get("text", "")
            if item["kind"] == "definition":
                matched = int(item["expected"]["source"] in answer.get("cited_sources", []))
                total = 1
            else:
                matched = sum(fact_present(k, v, text) for k, v in item["expected"].items())
                total = len(item["expected"])
            cited = answer.get("cited_event_ids", [])
            emitted = view.event_ids()
            home, away = view.match["home_team"]["id"], view.match["away_team"]["id"]
            score = (view.snapshot["score"][str(home)], view.snapshot["score"][str(away)])
            leak = leaks(answer, emitted, score, view.clock["minute"]) if "text" in answer else []
            metrics = {
                "facts_matched": matched,
                "facts_total": total,
                "fact_accuracy": matched / total,
                "cited": len(cited),
                "cited_valid": sum(i in emitted for i in cited),
                "citation_ok": 1.0 if not cited else sum(i in emitted for i in cited) / len(cited),
                "leaks": leak,
            }
            judge_score, justification = await judge.grade(item, answer, metrics)
            rows.append(
                {
                    "config": config.name,
                    "id": item["id"],
                    "kind": item["kind"],
                    "question": item["question"],
                    "stop_minute": item["stop_minute"],
                    "expected": item["expected"],
                    "answer": text,
                    "error": answer.get("error"),
                    "cited_event_ids": cited,
                    "cited_sources": answer.get("cited_sources", []),
                    "tools_used": answer.get("tools_used", []),
                    "latency_s": answer["latency_s"],
                    "attempts": answer.get("attempts", 1),
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "model_calls": usage.get("model_calls", 0),
                    "cost_usd": cost,
                    "judge": judge.name,
                    "judge_score": judge_score,
                    "judge_justification": justification,
                    **metrics,
                }
            )
    definition_items = [i for i in items if i["kind"] == "definition"]
    retrieval = None
    if kb is not None and definition_items:
        hits1 = hits3 = 0
        for item in definition_items:
            sources = [hit["source"] for hit in kb.search(item["question"], 3)]
            hits1 += sources[:1] == [item["expected"]["source"]]
            hits3 += item["expected"]["source"] in sources
        retrieval = {
            "questions": len(definition_items),
            "hit_at_1": round(hits1 / len(definition_items), 4),
            "hit_at_3": round(hits3 / len(definition_items), 4),
        }
    return {"rows": rows, "summary": summarize(rows, configs), "retrieval": retrieval}


def summarize(rows: list[dict], configs: list[Config]) -> list[dict]:
    summary = []
    for config in configs:
        mine = [r for r in rows if r["config"] == config.name]
        if not config.available:
            summary.append({"config": config.name, "skipped": config.reason})
            continue
        cited = sum(r["cited"] for r in mine)
        answered = [r for r in mine if not r["error"]]
        latencies = [r["latency_s"] for r in answered]  # Failed calls would distort latency.
        judged = [r["judge_score"] for r in mine if r["judge_score"] is not None]
        summary.append(
            {
                "config": config.name,
                "questions": len(mine),
                "errors": sum(bool(r["error"]) for r in mine),
                "factual_accuracy": round(statistics.mean(r["fact_accuracy"] for r in mine), 4),
                "factual_accuracy_answered": round(
                    statistics.mean(r["fact_accuracy"] for r in answered), 4
                )
                if answered
                else None,
                "citation_validity": round(sum(r["cited_valid"] for r in mine) / cited, 4)
                if cited
                else None,
                "leakage": sum(bool(r["leaks"]) for r in mine),
                "latency_p50_s": percentile(latencies, 0.5),
                "latency_p95_s": percentile(latencies, 0.95),
                "avg_tool_calls": round(statistics.mean(len(r["tools_used"]) for r in answered), 3)
                if answered
                else 0,
                "model_calls": sum(r.get("model_calls", 0) for r in mine),
                "input_tokens": sum(r.get("input_tokens", 0) for r in mine),
                "output_tokens": sum(r.get("output_tokens", 0) for r in mine),
                "cost_usd": round(sum(r.get("cost_usd", 0) for r in mine), 6),
                "retried": sum(r.get("attempts", 1) > 1 for r in mine),
                "judge": mine[0]["judge"] if mine else None,
                "judge_avg": round(statistics.mean(judged), 3) if judged else None,
            }
        )
    return summary


def write_outputs(result: dict, out: Path, human_csv: Path | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "| Configuration | Answered | Factual accuracy (all / answered) | Citation validity | "
        "Leakage | Latency p50 / p95 (s) | Avg tool calls | Tokens in / out | Cost (USD) | "
        "Judge (1–5) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in result["summary"]:
        if "skipped" in s:
            lines.append(f"| {s['config']} | skipped: {s['skipped']} | | | | | | | | |")
            continue
        validity = "n/a" if s["citation_validity"] is None else f"{s['citation_validity']:.0%}"
        answered = s["questions"] - s["errors"]
        on_answered = (
            "n/a"
            if s.get("factual_accuracy_answered") is None
            else f"{s['factual_accuracy_answered']:.0%}"
        )
        lines.append(
            f"| {s['config']} | {answered}/{s['questions']} | {s['factual_accuracy']:.0%} / "
            f"{on_answered} | {validity} | {s['leakage']} | "
            f"{s['latency_p50_s']} / {s['latency_p95_s']} | {s['avg_tool_calls']} | "
            f"{s.get('input_tokens', 0):,} / {s.get('output_tokens', 0):,} | "
            f"{s.get('cost_usd', 0):.4f} | {s['judge_avg']} ({s['judge']}) |"
        )
    if result.get("retrieval"):
        r = result["retrieval"]
        lines.append(
            f"\nDefinition retrieval ({r['questions']} questions): hit@1 {r['hit_at_1']:.0%}, "
            f"hit@3 {r['hit_at_3']:.0%}."
        )
    (out / "results.md").write_text("\n".join(lines) + "\n")
    chart(result, out / "results.png")
    if human_csv is not None and not human_csv.exists():
        export_human(result["rows"], human_csv)


def chart(result: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ran = [s for s in result["summary"] if "skipped" not in s]
    metrics = {
        "Factual accuracy": lambda s: s["factual_accuracy"],
        "Citation validity": lambda s: s["citation_validity"] or 0,
        "No leakage": lambda s: 1 - s["leakage"] / max(1, s["questions"]),
        "Judge / 5": lambda s: (s["judge_avg"] or 0) / 5,
    }
    figure, axis = plt.subplots(figsize=(max(6, 2.2 * len(ran) + 2), 4), dpi=150)
    width = 0.8 / len(metrics)
    palette = ["#1f6feb", "#2da44e", "#9a6700", "#8250df"]
    for index, (label, getter) in enumerate(metrics.items()):
        xs = [i + (index - (len(metrics) - 1) / 2) * width for i in range(len(ran))]
        values = [getter(s) for s in ran]
        axis.bar(xs, values, width, label=label, color=palette[index])
        for x, v in zip(xs, values, strict=True):
            axis.text(x, v + 0.01, f"{v:.0%}", ha="center", va="bottom", fontsize=7)
    axis.set_xticks(range(len(ran)), [s["config"] for s in ran])
    axis.set_ylim(0, 1.15)
    axis.set_ylabel("Share (higher is better)")
    axis.set_title("Touchline+ evaluation by configuration")
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


HUMAN_FIELDS = [
    "item",
    "config",
    "question",
    "stop_minute",
    "answer",
    "expected_facts",
    "tools_used",
    "judge",
    "judge_score",
    "judge_justification",
    "human_score",
    "human_notes",
]


def export_human(rows: list[dict], path: Path, count: int = 20) -> None:
    import csv

    answered = [r for r in rows if not r["error"]]
    step = max(1, len(answered) // count)
    chosen = answered[::step][:count]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, HUMAN_FIELDS)
        writer.writeheader()
        for index, row in enumerate(chosen, start=1):
            writer.writerow(
                {
                    "item": f"h{index:02}",
                    "config": row["config"],
                    "question": row["question"],
                    "stop_minute": row["stop_minute"],
                    "answer": row["answer"],
                    "expected_facts": json.dumps(row["expected"]),
                    "tools_used": " → ".join(t["tool"] for t in row["tools_used"]),
                    "judge": row["judge"],
                    "judge_score": row["judge_score"],
                    "judge_justification": row["judge_justification"],
                    "human_score": "",
                    "human_notes": "",
                }
            )


def main(argv=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset", choices=["all", "ci"], default="all")
    parser.add_argument("--configs", help="Comma-separated names, e.g. langgraph/offline")
    parser.add_argument("--out", type=Path, default=HERE)
    parser.add_argument("--no-human-export", action="store_true")
    parser.add_argument("--model", help="Gemini model to evaluate (default: GAME_GEMINI_MODEL)")
    parser.add_argument("--judge-model", help="Different Gemini model to use as the judge")
    parser.add_argument("--pause", type=float, default=0, help="Seconds between questions")
    parser.add_argument("--retries", type=int, default=0, help="Retries on 429/5xx errors")
    args = parser.parse_args(argv)
    base = Settings(trace_log="")
    if args.model:
        base = base.model_copy(update={"gemini_model": args.model})
    items = json.loads((HERE / "questions.json").read_text())
    if args.subset == "ci":
        items = [i for i in items if i["id"] in CI_SUBSET]
    configs = discover(base)
    if args.configs:
        wanted = set(args.configs.split(","))
        for config in configs:
            if config.name not in wanted:
                config.available, config.reason = False, "not selected"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        kb = knowledge(base, Path(folder)) if base.rag_enabled else None
        result = asyncio.run(
            run(
                items,
                configs,
                base,
                kb,
                judge_model=args.judge_model,
                pause=args.pause,
                retries=args.retries,
            )
        )
    result["model"] = base.gemini_model
    result["judge_model"] = args.judge_model
    result["prices_usd_per_million"] = {**DEFAULT_PRICES, **base.model_prices}.get(
        base.gemini_model
    )
    result["subset"] = args.subset
    human = None if args.no_human_export else args.out / "human_grading.csv"
    write_outputs(result, args.out, human)
    print((args.out / "results.md").read_text())
    return result


if __name__ == "__main__":
    main()
