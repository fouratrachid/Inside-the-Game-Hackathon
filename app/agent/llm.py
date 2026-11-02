"""One chat-model interface for the agent, selected by settings: Gemini, Foundry or Ollama.

Constructing a model makes no network calls, so the app starts without credentials; tests
inject a fake model instead of calling `build_model`.
"""

from fastapi import HTTPException
from langchain_core.language_models import BaseChatModel

from app.config import Settings

PROVIDER_LABELS = {"gemini": "Gemini", "foundry": "Microsoft Foundry", "ollama": "Ollama"}


def model_name(settings: Settings) -> str:
    return {
        "gemini": settings.gemini_model,
        "foundry": settings.foundry_deployment,
        "ollama": settings.ollama_model,
    }[settings.chat_provider]


def build_model(settings: Settings) -> BaseChatModel:
    provider = settings.chat_provider
    timeout = min(settings.chat_timeout_seconds, 30)
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            base_url=settings.ollama_url,
            model=settings.ollama_model,
            temperature=0.2,
            num_predict=600,
        )
    if provider == "foundry":
        from langchain_openai import ChatOpenAI

        # Same Azure OpenAI v1 endpoint the original workflow calls directly.
        return ChatOpenAI(
            base_url=settings.foundry_endpoint.rstrip("/") + "/openai/v1",
            api_key=settings.foundry_api_key.get_secret_value(),
            model=settings.foundry_deployment,
            temperature=0.2,
            max_completion_tokens=600,
            timeout=timeout,
            max_retries=2,
        )
    key = settings.gemini_api_key.get_secret_value()
    if not key:
        raise HTTPException(503, "Configure server-side model credentials to enable chat.")
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        api_key=key,
        temperature=0.2,
        max_tokens=600,
        timeout=timeout,
        retries=2,
        thinking_level="low",
    )
