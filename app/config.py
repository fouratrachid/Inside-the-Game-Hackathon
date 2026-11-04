"""Environment-based application configuration."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GAME_", env_file=".env", extra="ignore")

    app_name: str = "Inside the Game"
    # Touchline+: which chat pipeline answers questions (original MAF workflow or LangGraph).
    agent: Literal["maf", "langgraph"] = "langgraph"
    chat_provider: Literal["gemini", "foundry", "ollama", "offline"] = "gemini"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    agent_max_tool_rounds: int = Field(default=4, ge=1, le=8)
    chat_timeout_seconds: float = Field(default=45, gt=0, le=300)
    # Touchline+ momentum shifts (Phase 3).
    shift_threshold: float = Field(default=0.03, gt=0)
    shift_window_seconds: float = Field(default=300, gt=0)
    shift_hold_seconds: float = Field(default=180, ge=0)
    shift_debounce_seconds: float = Field(default=300, ge=0)
    # Touchline+ Phase 4: observability, RAG, guardrails, cache and cost control.
    trace_log: str = "logs/traces.jsonl"  # Empty disables the local JSON-lines trace log.
    langfuse_public_key: SecretStr = SecretStr("")
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: str = "https://cloud.langfuse.com"
    rag_enabled: bool = True
    rag_path: str = "data/chroma"
    rag_collection: str = "touchline_knowledge"
    rag_embedder: Literal["fastembed", "gemini", "hash"] = "fastembed"
    rag_fastembed_model: str = "BAAI/bge-small-en-v1.5"
    rag_build_on_startup: bool = True
    rag_top_k: int = Field(default=3, ge=1, le=10)
    chat_rate_limit: int = Field(default=10, ge=0)  # Questions per session per window.
    chat_rate_window_seconds: float = Field(default=60, gt=0)
    cache_ttl_seconds: float = Field(default=600, ge=0)
    cache_max_entries: int = Field(default=256, ge=0)
    session_budget_usd: float = Field(default=0.10, ge=0)  # 0 disables the budget.
    model_prices: dict[str, tuple[float, float]] = Field(default_factory=dict)
    # Touchline+ Phase 6: deployment.
    source: Literal["statsbomb", "synthetic", "both"] = "statsbomb"
    # With the Gemini provider and no key, answer with the offline baseline instead of 503.
    chat_fallback_offline: bool = True
    max_sessions: int = Field(default=500, ge=1)
    session_ttl_seconds: float = Field(default=3 * 3600, gt=0)
    note_max_per_session: int = Field(default=12, ge=0)  # Matches the UI's 12-note limit.
    note_min_interval_seconds: float = Field(default=20, ge=0)  # Matches the UI cooldown.
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.8-flash"
    explanation_provider: Literal["off", "template", "foundry"] = "template"
    foundry_endpoint: str = ""
    foundry_deployment: str = ""
    foundry_api_key: SecretStr = SecretStr("")
    explanation_timeout_seconds: float = Field(default=10, gt=0, le=60)
    explanation_max_calls: int = Field(default=12, ge=0, le=100)
    explanation_interval_seconds: float = Field(default=30, ge=0)

    @model_validator(mode="after")
    def validate_foundry(self):
        if self.chat_provider == "ollama":
            url = urlsplit(self.ollama_url)
            if url.scheme not in ("http", "https") or not url.hostname:
                raise ValueError("Ollama URL must be an http(s) URL")
        if self.explanation_provider == "foundry" or self.chat_provider == "foundry":
            endpoint = urlsplit(self.foundry_endpoint)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
                or endpoint.path not in ("", "/")
            ):
                raise ValueError("Foundry endpoint must be an HTTPS resource root URL")
            if not self.foundry_deployment.strip() or not self.foundry_api_key.get_secret_value():
                raise ValueError("Foundry mode requires a deployment name and API key")
        return self
