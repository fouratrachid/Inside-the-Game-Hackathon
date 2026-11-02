# Touchline+ architecture

_Updated at the end of every phase. Current state: **Phase 6** (deployment)._

## System

```mermaid
flowchart LR
    SB[(StatsBomb open data<br/>or SyntheticSource)] --> Main[app/main.py FastAPI]
    Main -->|create| Store[SessionStore]
    Main --> Replay[app/replay.py]
    Replay --> Analytics[MatchAnalytics]
    Replay -->|after yield| Shifts[app/shifts.py<br/>ShiftDetector]
    Shifts -->|SSE momentum_shift| Browser
    Shifts -->|record_shift| Session
    Replay -->|record after yield| Session[MatchSession<br/>history · players · minutes]
    Store --- Session
    Replay -->|SSE match+session_id / update| Browser[app.js + chat.js]
    Browser -->|POST /chat question + session_id| Main
    Main -->|GAME_AGENT=langgraph| Agent[app/agent/service.py]
    Agent -->|session.view frozen| Graph[app/agent/graph.py]
    Graph <--> Tools[app/agent/tools.py<br/>7 read-only tools]
    Tools --> View[SessionView]
    Graph --> LLM[(Gemini / Foundry / Ollama)]
    Agent --> Guard[app/guardrails.py<br/>input flags · rate limit · output checks]
    Agent --> Usage[app/usage.py<br/>cache · cost · budget]
    Agent --> Trace[app/observability.py<br/>JSONL · Langfuse]
    Tools --> RAG[app/rag<br/>Chroma + embeddings] --> KN[(knowledge/*.md)]
    Browser -->|POST /chat/stream| Main
    Main -->|GAME_AGENT=maf| MAF[app/chat.py + chat_workflow.py] --> LLM2[(Gemini / Foundry)]
```

## Data flow

```mermaid
sequenceDiagram
    participant B as Browser
    participant S as FastAPI
    participant M as MatchSession
    participant G as LangGraph
    participant T as Tools
    participant L as LLM
    B->>S: POST /chat {question, mode, session_id}
    S->>M: view() (frozen)
    S->>G: run_agent
    loop ≤ 4 rounds
      G->>L: messages + tool schemas
      L-->>G: tool calls
      G->>T: run on frozen view
      T-->>G: results with event IDs
    end
    L-->>G: {text, cited_event_ids, snapshot_minute}
    G->>G: answer → validator (ids emitted? minute ≤ clock? retry once)
    G-->>B: answer + evidence + tools_used trace
```

## Momentum shift flow (Phase 3)

```mermaid
sequenceDiagram
    participant R as replay_updates
    participant D as ShiftDetector
    participant B as Browser (app.js / chat.js)
    R-->>B: update (event N)
    R->>D: consume(update N)
    D-->>R: shift (gap held 3 min)
    R-->>B: momentum_shift {sequences, chain, narration}
    B->>B: chart marker + timeline note
    B->>B: click → numbered arrows on pitch
```

## Production request flow (Phase 4)

```mermaid
sequenceDiagram
    participant UI as chat.js
    participant API as /chat/stream
    participant S as MatchAgent
    participant G as Graph
    participant T as Tracer
    UI->>API: question + session_id
    API->>S: rate limit
    S->>T: root trace (session, match, provider)
    S->>S: input guard → cache → budget
    S->>G: stream_agent
    G->>T: spans: generation, tools, validator
    G-->>UI: token events
    G-->>S: validated answer + usage
    S-->>UI: final {citations, sources, trace, cost, session_usage}
```

## Evaluation (Phase 5)

```mermaid
flowchart LR
    Q[eval/questions.json] --> R[eval/run.py]
    R -->|replay_to stop minute| S[MatchSession]
    R --> C1[langgraph/offline] & C2[langgraph/gemini] & C3[maf/gemini] & C4[langgraph/ollama]
    C1 & C2 & C3 & C4 --> M[metrics + judge]
    M --> O[results.json / .md / .png]
    M --> H[human_grading.csv] --> A[agreement.py]
```

## Deployment (Phase 6)

```mermaid
flowchart LR
    Repo[GitHub] --> CI[Actions: lint · tests · eval subset · docker build + /health]
    Repo --> Render[Render free web service<br/>render.yaml]
    Render --> Img[Docker image<br/>non-root · $PORT · healthcheck]
    Img --> App[FastAPI app]
    App --> Src[GAME_SOURCE=both<br/>synthetic + StatsBomb]
    App --> Chat[LangGraph agent<br/>Gemini or offline fallback]
```
