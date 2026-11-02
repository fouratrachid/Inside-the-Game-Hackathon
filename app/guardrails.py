"""Guardrails: input checks, rate limits, untrusted-data delimiting and output checks.

The injection detector *flags* questions (recorded in the trace and tightened in the prompt);
it never silently drops them. Requests for secrets or the system prompt, and clearly
off-topic requests, are refused before any model call. Output checks reject answers that leak
secrets, the system prompt, a scoreline other than the current one, or a later minute.
"""

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

MAX_QUESTION_CHARS = 500

INJECTION_PATTERNS = {
    "override_instructions": (
        r"\b(ignore|disregard|forget|override)\b.{0,40}"
        r"\b(instruction|rule|prompt|guideline|above|previous)s?\b"
    ),
    "role_play": r"\b(you are now|act as|pretend (to be|you)|developer mode|jailbreak|DAN)\b",
    "prompt_extraction": (
        r"\b(system prompt|initial prompt|hidden prompt|"
        r"(show|reveal|print|repeat|tell me|what are|what is|list)\b.{0,20}"
        r"\byour (instructions|prompt|rules))\b"
    ),
    "secret_request": (
        r"\b(api[ _-]?key|secret|password|credential|access token|env(ironment)? var"
        r"|settings file|\.env)\b"
    ),
    "future_request": (
        r"\b(final (score|result)|full[- ]time (score|result)|who (won|wins)"
        r"|end of the match|how does it end)\b"
    ),
    "markup_injection": r"</?(system|tool_result|document|question|instructions?)>",
}
FOOTBALL_TERMS = re.compile(
    r"\b(match|game|team|player|goal|shot|xg|xt|pass|press|possession|tilt|momentum|chance|"
    r"half|minute|score|attack|defen[cs]e|keeper|corner|foul|card|tackle|network|formation|"
    r"lead|winning|losing|danger|threat|play|ball|field|pitch|stat|metric|define|explain|"
    r"what is|what does|who|why|how)\b",
    re.IGNORECASE,
)
OFF_TOPIC = re.compile(
    r"\b(poem|recipe|stock|crypto|weather|homework|essay"
    r"|write (me )?(a )?(code|program|song|story)|translate|python|javascript|sql)\b",
    re.IGNORECASE,
)
REFUSAL_SECRETS = (
    "I can't share instructions, keys or server settings. Ask me about the match so far."
)
REFUSAL_OFF_TOPIC = "I can only answer questions about this match replay so far."


@dataclass
class InputCheck:
    flags: list[str] = field(default_factory=list)
    refusal: str | None = None


def check_question(question: str) -> InputCheck:
    """Flag likely injection; refuse secret/system-prompt requests and off-topic asks."""
    if len(question) > MAX_QUESTION_CHARS:
        return InputCheck(["too_long"], "Please keep questions under 500 characters.")
    flags = [
        name
        for name, pattern in INJECTION_PATTERNS.items()
        if re.search(pattern, question, re.IGNORECASE)
    ]
    if {"secret_request", "prompt_extraction"} & set(flags):
        return InputCheck(flags, REFUSAL_SECRETS)
    if OFF_TOPIC.search(question) and not FOOTBALL_TERMS.search(question):
        return InputCheck([*flags, "off_topic"], REFUSAL_OFF_TOPIC)
    return InputCheck(flags)


def wrap_data(kind: str, content: str, **attributes) -> str:
    """Delimit untrusted text so the model can tell data from instructions."""
    content = re.sub(r"</?\s*(" + kind + r"|system|instructions?)\s*>", "[tag removed]", content)
    attrs = "".join(f' {k}="{str(v).replace(chr(34), "")}"' for k, v in attributes.items())
    return f"<{kind}{attrs}>\n{content}\n</{kind}>"


SCORE = re.compile(r"\b(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\b")
MINUTE = re.compile(r"\b(\d{1,3})\s*(?:′|'|’|(?:st|nd|rd|th)? ?min(?:ute)?s?\b)", re.IGNORECASE)


def check_output(
    text: str,
    *,
    score: tuple[int, int] | None,
    clock_minute: int,
    secrets: list[str],
    system_prompt: str,
) -> list[str]:
    """Return problems with an answer; empty means it passes."""
    problems = []
    lowered = text.lower()
    if any(secret and secret.lower() in lowered for secret in secrets if len(secret) >= 6):
        problems.append("secret_leak")
    words = system_prompt.lower().split()
    if any(" ".join(words[i : i + 8]) in lowered for i in range(0, max(0, len(words) - 8), 4)):
        problems.append("system_prompt_leak")
    if score is not None:
        allowed = {score, score[::-1]}
        for match in SCORE.finditer(text):
            pair = (int(match.group(1)), int(match.group(2)))
            # Ignore obvious non-scores such as minute ranges ("0-45", "15 to 30").
            if max(pair) <= 9 and pair not in allowed:
                problems.append("score_mismatch")
                break
    for match in MINUTE.finditer(text):
        if int(match.group(1)) > clock_minute + 1:
            problems.append("future_minute")
            break
    return problems


class RateLimiter:
    """Sliding-window limit per key (e.g. per session)."""

    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self.calls: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        calls = self.calls[key]
        while calls and now - calls[0] > self.window:
            calls.popleft()
        if len(calls) >= self.limit:
            return False
        calls.append(now)
        return True
