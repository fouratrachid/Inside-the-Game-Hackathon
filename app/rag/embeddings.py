"""Embedding backends behind one small interface.

- `fastembed` (default): local ONNX model, downloaded once (BAAI/bge-small-en-v1.5).
- `gemini`: Google embeddings via langchain-google-genai (needs GAME_GEMINI_API_KEY).
- `hash`: deterministic bag-of-words hashing; offline, no model, good enough for tests/CI.
"""

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Deterministic hashed bag of words (+ bigrams), L2-normalised."""

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions
        self.name = f"hash-{dimensions}"

    def _vector(self, text: str) -> list[float]:
        words = re.findall(r"[a-z0-9]+", text.lower())
        vector = [0.0] * self.dimensions
        for token in words + [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]:
            digest = int(hashlib.md5(token.encode()).hexdigest(), 16)
            vector[digest % self.dimensions] += 1.0 if digest & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)


class FastEmbedder:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model)
        self.name = f"fastembed-{model}"

    def embed_documents(self, texts):
        return [list(map(float, v)) for v in self.model.embed(texts)]

    def embed_query(self, text):
        return [float(v) for v in next(iter(self.model.query_embed(text)))]


class GeminiEmbedder:
    def __init__(self, api_key: str, model: str = "models/gemini-embedding-001"):
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        self.model = GoogleGenerativeAIEmbeddings(model=model, google_api_key=api_key)
        self.name = f"gemini-{model}"

    def embed_documents(self, texts):
        return self.model.embed_documents(texts)

    def embed_query(self, text):
        return self.model.embed_query(text)


def build_embedder(settings) -> Embedder:
    kind = settings.rag_embedder
    if kind == "hash":
        return HashEmbedder()
    if kind == "gemini":
        return GeminiEmbedder(settings.gemini_api_key.get_secret_value())
    return FastEmbedder(settings.rag_fastembed_model)
