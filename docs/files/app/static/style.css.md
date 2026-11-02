# app/static/style.css

## Purpose
All styles for the matchroom and broadcast overlay.

## How it works
Phase 2 adds `.chat-trace` — a small monospace muted line under answers and timeline notes showing the agent's tool trace — with a larger size inside `.broadcast-overlay`.

```mermaid
flowchart LR
    chat.js -->|p.chat-trace| DOM --> style.css
```

## Connections
Loaded by `index.html` and `overlay.html`.

## What changed
Added the `.chat-trace` rules only.

**Phase 3:** `.pitch-actions`, `.shift-marker`, `.chain-arrow` (dash animation via `pathLength=1`), `.chain-step`, `.ai-note.clickable`, `.shift-note`, reduced-motion fallback.

## Tests
Visual only.

## Limitations and future work
None.
