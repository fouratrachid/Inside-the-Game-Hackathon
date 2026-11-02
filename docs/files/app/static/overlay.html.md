# app/static/overlay.html

## Purpose
The broadcast overlay page (`/`): controls, scoreboard, momentum, pitch, stats, passing network and the Match intelligence panel.

## How it works
Phase 3 adds a `Clear highlight` button (`#clearHighlight`, hidden by default) next to `Following live` in the pitch card header, inside a new `.pitch-actions` wrapper.

```mermaid
flowchart LR
    index.html --> app.js & chat.js & style.css
    app.js -->|highlightChain| livePitch[#livePitch]
    app.js -->|show/hide| clear[#clearHighlight]
```

## Connections
Served by `app/main.py`; scripts `app.js`, `chat.js`.

## What changed
Only the pitch header markup.

## Tests
Manual Playwright check (see the Phase 3 report).

## Limitations and future work
None.
