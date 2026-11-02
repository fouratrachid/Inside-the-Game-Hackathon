"""Tracing for the agent: one trace per question/note, spans for graph nodes and tool calls.

Backends are optional and composable:
- no backend → every span call is a cheap no-op;
- `JsonlBackend` → one JSON line per trace in `logs/traces.jsonl` (inspect runs offline);
- `LangfuseBackend` → live spans in Langfuse when `GAME_LANGFUSE_*` keys are configured.
"""

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _size(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str))
    except TypeError, ValueError:
        return 0


class Span:
    """A node in a trace. Use as a context manager or call `end()` explicitly."""

    def __init__(self, tracer, name, kind="span", parent=None, input=None, metadata=None):
        self.tracer = tracer
        self.id = uuid.uuid4().hex[:16]
        self.trace_id = parent.trace_id if parent else uuid.uuid4().hex
        self.parent = parent
        self.name = name
        self.kind = kind
        self.input = input
        self.output = None
        self.metadata = dict(metadata or {})
        self.usage: dict = {}
        self.cost: float | None = None
        self.level = "DEFAULT"
        self.events: list[dict] = []
        self.started = time.time()
        self.duration_ms: float | None = None
        self.handles = {}
        for backend in tracer.backends:
            try:
                self.handles[backend] = backend.start(self)
            except Exception as error:  # Observability must never break answering.
                logger.warning("Tracing backend start failed: %s", type(error).__name__)

    def child(self, name, kind="span", input=None, metadata=None) -> Span:
        return Span(self.tracer, name, kind, self, input, metadata)

    def event(self, name: str, **metadata) -> None:
        self.events.append({"name": name, **metadata})

    def end(self, output=None, metadata=None, usage=None, cost=None, level=None) -> None:
        if self.duration_ms is not None:
            return
        self.output = output
        self.metadata.update(metadata or {})
        self.usage = usage or self.usage
        self.cost = cost if cost is not None else self.cost
        self.level = level or self.level
        self.duration_ms = round((time.time() - self.started) * 1000, 2)
        for backend, handle in self.handles.items():
            try:
                backend.end(self, handle)
            except Exception as error:
                logger.warning("Tracing backend end failed: %s", type(error).__name__)

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if error is not None:
            self.end(metadata={"error": type(error).__name__}, level="ERROR")
        else:
            self.end(self.output)
        return False


class Tracer:
    def __init__(self, backends=()):
        self.backends = list(backends)

    @property
    def enabled(self) -> bool:
        return bool(self.backends)

    def trace(self, name, *, input=None, session_id=None, tags=(), metadata=None) -> Span:
        return Span(
            self,
            name,
            "agent",
            None,
            input,
            {**(metadata or {}), "session_id": session_id, "tags": list(tags)},
        )


class JsonlBackend:
    """Collects each trace in memory and appends it as one JSON line when the root ends."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.open: dict[str, list] = {}

    def start(self, span: Span):
        self.open.setdefault(span.trace_id, [])
        return None

    def end(self, span: Span, handle) -> None:
        record = {
            "id": span.id,
            "parent": span.parent.id if span.parent else None,
            "name": span.name,
            "kind": span.kind,
            "input": span.input,
            "output": span.output,
            "output_size": _size(span.output),
            "metadata": span.metadata,
            "usage": span.usage,
            "cost": span.cost,
            "level": span.level,
            "events": span.events,
            "duration_ms": span.duration_ms,
        }
        spans = self.open.setdefault(span.trace_id, [])
        spans.append(record)
        if span.parent is None:
            line = {
                "trace_id": span.trace_id,
                "name": span.name,
                "started": span.started,
                "session_id": span.metadata.get("session_id"),
                "tags": span.metadata.get("tags", []),
                "spans": self.open.pop(span.trace_id, spans),
            }
            with self.lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(line, default=str) + "\n")


LANGFUSE_KINDS = {"agent", "generation", "tool", "chain", "retriever", "guardrail", "span"}


class LangfuseBackend:
    """Mirrors spans into Langfuse (SDK v3+ OpenTelemetry API)."""

    def __init__(self, public_key: str, secret_key: str, host: str, client=None):
        if client is None:
            from langfuse import Langfuse

            client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        self.client = client

    def start(self, span: Span):
        kind = span.kind if span.kind in LANGFUSE_KINDS else "span"
        if span.parent is None:
            from langfuse import propagate_attributes

            context = propagate_attributes(
                session_id=span.metadata.get("session_id"),
                tags=[str(tag) for tag in span.metadata.get("tags", [])],
                trace_name=span.name,
            )
            context.__enter__()
            observation = self.client.start_observation(
                name=span.name, as_type=kind, input=span.input, metadata=span.metadata
            )
            return (observation, context)
        parent = span.parent.handles.get(self)
        owner = parent[0] if parent else self.client
        return (
            owner.start_observation(
                name=span.name, as_type=kind, input=span.input, metadata=span.metadata
            ),
            None,
        )

    def end(self, span: Span, handle) -> None:
        observation, context = handle
        details = {"output": span.output, "metadata": span.metadata, "level": span.level}
        if span.kind == "generation":
            details["model"] = span.metadata.get("model")
            if span.usage:
                details["usage_details"] = {k: int(v) for k, v in span.usage.items()}
            if span.cost is not None:
                details["cost_details"] = {"total": float(span.cost)}
        observation.update(**details)
        observation.end()
        if context is not None:
            context.__exit__(None, None, None)
            self.client.flush()


def build_tracer(settings) -> Tracer:
    backends = []
    if settings.trace_log:
        backends.append(JsonlBackend(settings.trace_log))
    public = settings.langfuse_public_key.get_secret_value()
    secret = settings.langfuse_secret_key.get_secret_value()
    if public and secret:
        try:
            backends.append(LangfuseBackend(public, secret, settings.langfuse_host))
        except Exception as error:
            logger.warning("Langfuse disabled: %s", type(error).__name__)
    return Tracer(backends)
