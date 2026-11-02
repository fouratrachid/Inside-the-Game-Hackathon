"""Token and cost accounting, the per-session budget and the answer cache."""

import re
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass

# USD per one million tokens (input, output). Placeholders: verify against your provider's
# current price list and override with GAME_MODEL_PRICES='{"model": [in, out]}'.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.30, 2.50),
    "gpt-4.1-mini": (0.40, 1.60),
    "qwen2.5:7b-instruct": (0.0, 0.0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int, prices: dict) -> float:
    """Cost of one call; unknown models are priced at zero (and flagged in the trace)."""
    price_in, price_out = prices.get(model, (0.0, 0.0))
    return round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 8)


@dataclass
class SessionUsage:
    questions: int = 0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cache_hits: int = 0
    blocked: int = 0

    def add(self, usage: dict) -> None:
        self.model_calls += usage.get("model_calls", 0)
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        self.cost_usd = round(self.cost_usd + usage.get("cost_usd", 0.0), 8)

    def as_dict(self, budget: float | None = None) -> dict:
        data = asdict(self)
        data["budget_usd"] = budget
        data["budget_remaining_usd"] = (
            None if budget is None else round(max(0.0, budget - self.cost_usd), 8)
        )
        return data


def normalize_question(question: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", question.lower())).strip()


class AnswerCache:
    """In-memory LRU with TTL. Keys: normalized question, match, clock bucket, mode, provider."""

    def __init__(self, max_entries: int = 256, ttl_seconds: float = 600):
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        self.entries: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()

    @staticmethod
    def key(question, match_id, clock, mode, provider) -> tuple:
        bucket = (clock or {}).get("period"), (clock or {}).get("minute")
        return (normalize_question(question), match_id, bucket, mode, provider)

    def get(self, key: tuple) -> dict | None:
        item = self.entries.get(key)
        if item is None:
            return None
        stored, value = item
        if time.monotonic() - stored > self.ttl:
            del self.entries[key]
            return None
        self.entries.move_to_end(key)
        return value

    def put(self, key: tuple, value: dict) -> None:
        if self.max_entries <= 0:
            return
        self.entries[key] = (time.monotonic(), value)
        self.entries.move_to_end(key)
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)
