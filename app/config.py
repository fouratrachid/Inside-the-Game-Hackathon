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
    chat_provider: Literal["gemini", "foundry", "ollama"] = "gemini"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    agent_max_tool_rounds: int = Field(default=4, ge=1, le=8)
    chat_timeout_seconds: float = Field(default=45, gt=0, le=300)
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
