# Touchline+ production image (Phase 6). Build: docker build -t touchline-plus .
# Run:   docker run -p 8000:8000 -e GAME_GEMINI_API_KEY=... touchline-plus
# Without a key the app still works: the synthetic match replays and chat uses the labelled
# offline baseline.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime dependencies only (no dev tools), straight from the verified lock file.
RUN pip install pipenv==2026.6.1
COPY Pipfile Pipfile.lock ./
RUN pipenv install --deploy --system && pip uninstall -y pipenv

COPY app ./app
COPY knowledge ./knowledge

# Hosted defaults: synthetic match always available, StatsBomb catalogue when reachable,
# offline hash embeddings (no model download), small session store for free-tier memory.
ENV GAME_SOURCE=both \
    GAME_RAG_EMBEDDER=hash \
    GAME_RAG_PATH=/app/data/chroma \
    GAME_TRACE_LOG=/tmp/touchline-traces.jsonl \
    GAME_MAX_SESSIONS=50 \
    GAME_SESSION_BUDGET_USD=0.05 \
    PORT=8000

# Build the definitions index into the image so lookup_definition works on first request.
RUN python -m app.rag.ingest \
    && useradd --create-home --uid 10001 touchline \
    && chown -R touchline /app/data

USER touchline
EXPOSE 8000
# Bypass any HTTP(S)_PROXY: the check must hit this container's own port.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os, urllib.request as u; u.build_opener(u.ProxyHandler({})).open('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)"

# Render, Fly.io and Hugging Face Spaces each inject PORT; default 8000 locally.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
