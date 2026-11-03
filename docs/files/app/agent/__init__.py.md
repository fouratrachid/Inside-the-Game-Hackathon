# app/agent/__init__.py

## Purpose
Marks `app/agent/` as the Touchline+ agent package: `tools.py` (what the model can look up), `graph.py` (the LangGraph state machine), `llm.py` (providers) and `service.py` (the API-facing service).

## How it works
Contains only a docstring; modules are imported explicitly.

## Connections
```mermaid
flowchart LR
    main[app/main.py] --> service --> graph --> tools --> sessions[app/sessions.py]
    service --> llm --> providers[(Gemini / Foundry / Ollama)]
```

## What changed
New in Phase 2.

## Tests
Package imported by `tests/test_agent.py`.

## Limitations and future work
None.
