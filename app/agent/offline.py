"""A deterministic, rule-based stand-in for an LLM (`GAME_CHAT_PROVIDER=offline`).

It is not a language model. It routes a question to tools by keywords, then writes a short
answer from the tool results with real numbers and cited event IDs, in the same JSON format
the LangGraph validator expects. Uses: the evaluation baseline and CI subset (no API key),
and a public demo that works without credentials. Every answer goes through the same graph,
tools, validator and guards as a real model.
"""

import json
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

DEFINITION = re.compile(
    r"\b(what is|what's|define|definition|meaning|mean|explain|how is .* (calculated|"
    r"estimated|measured))\b",
    re.IGNORECASE,
)
METRIC = re.compile(
    r"\b(xg|expected goals|xt|expected threat|field tilt|possession|momentum|passing network|"
    r"freeze.frame|statsbomb)\b",
    re.IGNORECASE,
)
PLAYER = re.compile(r"\b((?:[A-Z][a-z]+ )*[A-Z][a-z]+ \d{1,2}|[A-Z][a-z]+ [A-Z][a-z]+)\b")


def _clean_question(messages) -> str:
    for message in messages:
        content = str(message.content)
        match = re.search(r"<question[^>]*>\n?(.*?)\n?</question>", content, re.DOTALL)
        if match:
            return match.group(1).strip()
    return ""


def _clock(messages) -> dict:
    for message in messages:
        if isinstance(message, HumanMessage):
            try:
                return json.loads(str(message.content).split("\n", 1)[0]).get("replay_clock") or {}
            except ValueError:
                continue
    return {}


def _results(messages) -> dict:
    results = {}
    for message in messages:
        if isinstance(message, ToolMessage):
            body = str(message.content)
            try:
                results[message.name] = json.loads(body.split("\n", 1)[1].rsplit("\n", 1)[0])
            except IndexError, ValueError:
                results[message.name] = {"error": "unreadable"}
    return results


def _window(question: str, minute: int) -> tuple[int, int] | None:
    q = question.lower()
    if match := re.search(r"between (\d+)\D+(\d+)", q):
        return int(match.group(1)), int(match.group(2))
    if match := re.search(r"first (\d+) minutes", q):
        return 0, int(match.group(1))
    if match := re.search(r"last (\d+) minutes", q):
        return max(0, minute + 1 - int(match.group(1))), minute + 1
    if "first half" in q:
        return 0, 45
    if "second half" in q:
        return 45, 90
    return None


def _fmt(value, digits=2):
    return "unknown" if value is None else f"{value:.{digits}f}"


class OfflineAnalyst(BaseChatModel):
    """Rule-based tool router + template writer. Deterministic; no network."""

    tool_names: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "offline-rule-based"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tool_names": [tool.name for tool in tools]})

    def _plan(self, question: str, clock: dict) -> list[tuple[str, dict]]:
        q = question.lower()
        calls: list[tuple[str, dict]] = []
        if "lookup_definition" in self.tool_names and DEFINITION.search(q) and METRIC.search(q):
            return [("lookup_definition", {"query": question})]
        window = _window(question, clock.get("minute") or 0)
        player = next(
            (m for m in PLAYER.findall(question) if not m.endswith(("FC", "United"))), None
        )
        if player and not re.match(r"^(Who|What|How|Which|Compare)\b", player):
            calls.append(("get_player_stats", {"name": player}))
        if window and re.search(r"compare|between|first|last|half|window|spell", q):
            if "momentum" in q or "on top" in q or "last" in q:
                calls.append(("get_momentum", {"window_min": window[1] - window[0]}))
            else:
                calls.append(("compare_periods", {"start_min": window[0], "end_min": window[1]}))
        if re.search(r"momentum|on top|pressure|control|dominat", q) and not calls:
            calls.append(("get_momentum", {"window_min": 10}))
        if not calls or re.search(r"score|shot|chance|xg|possession|tilt|pass", q):
            if not player:
                calls.append(("get_match_stats", {}))
        if re.search(r"shot|chance", q) and not player:
            calls.append(("get_recent_events", {"n": 5, "type": "Shot"}))
        return calls or [("get_match_stats", {})]

    def _write(self, question: str, clock: dict, results: dict) -> dict:
        q = question.lower()
        sentences, cited, sources = [], [], []
        stats = results.get("get_match_stats", {})
        teams = stats.get("teams") or {}
        names = list(teams)
        if "lookup_definition" in results:
            chunks = results["lookup_definition"].get("chunks") or []
            # Skip each file's "Sources:" preamble chunk; quote a definition section instead.
            usable = [c for c in chunks if not c["text"].split("\n", 1)[-1].startswith("Sources")]
            if usable:
                body = usable[0]["text"].split("\n", 1)[-1]
                sentences.append(" ".join(body.split()[:45]).rstrip(".,;") + ".")
                sources.append(usable[0]["source"])
            else:
                sentences.append("I don't have a definition for that yet.")
        player = results.get("get_player_stats")
        if player:
            if player.get("found"):
                sentences.append(
                    f"{player['name']} has {player['passes']} passes "
                    f"({player['completed_passes']} completed, {player['progressive_passes']} "
                    f"progressive), {player['shots']} shots worth {_fmt(player['xg'])} xG and "
                    f"{_fmt(player['xt_added'])} xT added so far."
                )
                cited.extend(player.get("recent_event_ids", [])[:2])
            else:
                sentences.append("I can't find that player in the events so far.")
        window = results.get("compare_periods")
        if window and "inside" in window:
            parts = [
                f"{team} {v['shots']} shots, {_fmt(v['xg'])} xG, {v['passes']} passes"
                for team, v in window["inside"].items()
            ]
            sentences.append(f"In {window['window']}: " + "; ".join(parts) + ".")
        momentum = results.get("get_momentum")
        if momentum and "xt_added" in momentum:
            values = ", ".join(f"{t} {_fmt(v)}" for t, v in momentum["xt_added"].items())
            leader = momentum.get("leading_team")
            lead = f"{leader} are on top" if leader else "Neither side is clearly on top"
            sentences.append(f"{lead}: xT added over the {momentum['window']} is {values}.")
        if len(names) == 2 and not player:
            home, away = teams[names[0]], teams[names[1]]
            if re.search(r"shot|chance|xg|better|danger", q):
                sentences.append(
                    f"Shots {home['shots']}-{away['shots']} ({home['shots_on_target']}-"
                    f"{away['shots_on_target']} on target), xG {_fmt(home['xg'])} vs "
                    f"{_fmt(away['xg'])}."
                )
            if "possession" in q:
                sentences.append(
                    f"Estimated possession is {_fmt(home['possession_pct'], 1)}% to "
                    f"{_fmt(away['possession_pct'], 1)}%."
                )
            if "tilt" in q or "territor" in q:
                sentences.append(
                    f"Field tilt is {_fmt(home['field_tilt_pct'], 1)}% to "
                    f"{_fmt(away['field_tilt_pct'], 1)}%."
                )
            if "pass" in q and "completion" in q:
                sentences.append(
                    f"Pass completion is {_fmt(home['pass_completion_pct'], 1)}% to "
                    f"{_fmt(away['pass_completion_pct'], 1)}%."
                )
        if len(names) == 2 and not player:
            if re.search(r"score|winning|lead", q) or not sentences:
                home, away = teams[names[0]], teams[names[1]]
                score = f"It is {names[0]} {home['goals']}-{away['goals']} {names[1]}."
                sentences.insert(0, score)
        recent = results.get("get_recent_events", {}).get("events") or []
        cited.extend(event["id"] for event in recent[:2])
        text = " ".join(sentences) or "I don't have enough match data to answer that yet."
        return {
            "text": text[:1150],
            "cited_event_ids": list(dict.fromkeys(cited))[:6],
            "snapshot_minute": clock.get("minute") or 0,
            "cited_sources": sources,
        }

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        question, clock = _clean_question(messages), _clock(messages)
        results = _results(messages)
        if not results:
            calls = [(n, a) for n, a in self._plan(question, clock) if n in self.tool_names]
            if calls:
                message = AIMessage(
                    content="",
                    tool_calls=[
                        {"name": name, "args": args, "id": f"offline-{index}"}
                        for index, (name, args) in enumerate(calls)
                    ],
                )
                return ChatResult(generations=[ChatGeneration(message=message)])
        answer = self._write(question, clock, results)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(json.dumps(answer)))])
