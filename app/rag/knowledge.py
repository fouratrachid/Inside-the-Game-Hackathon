"""The knowledge base the agent queries: embed the query, search the store."""

import logging

from app.rag.embeddings import Embedder, build_embedder
from app.rag.store import ChromaStore

logger = logging.getLogger(__name__)


def collection_name(settings) -> str:
    """One collection per embedder, so vectors of different dimensions never mix."""
    return f"{settings.rag_collection}-{settings.rag_embedder}"


class KnowledgeBase:
    def __init__(self, store, embedder: Embedder, top_k: int = 3):
        self.store = store
        self.embedder = embedder
        self.top_k = top_k

    def search(self, query: str, k: int | None = None) -> list[dict]:
        if not query.strip():
            return []
        return self.store.query(self.embedder.embed_query(query), k or self.top_k)


class LazyKnowledgeBase:
    """Builds the embedder and store on first use so app start-up stays fast and offline."""

    def __init__(self, settings):
        self.settings = settings
        self._kb: KnowledgeBase | None = None

    def ensure_index(self) -> KnowledgeBase:
        """Open the index, building it from knowledge/*.md if it is empty."""
        if self._kb is None:
            store = ChromaStore(self.settings.rag_path, collection_name(self.settings))
            embedder = build_embedder(self.settings)
            if store.count() == 0:
                from app.rag.ingest import ingest

                logger.warning(
                    "The definitions index %s is empty; building it from knowledge/*.md.",
                    collection_name(self.settings),
                )
                try:
                    report = ingest(store, embedder)
                except Exception as error:
                    logger.warning(
                        "Could not build the definitions index (%s). lookup_definition will "
                        "fail until you run: pipenv run python -m app.rag.ingest",
                        type(error).__name__,
                    )
                    raise ValueError(
                        "The definitions index is empty. Run: pipenv run python -m app.rag.ingest"
                    ) from error
                logger.warning("Built the definitions index: %s", report)
            self._kb = KnowledgeBase(store, embedder, self.settings.rag_top_k)
        return self._kb

    def search(self, query: str, k: int | None = None) -> list[dict]:
        return self.ensure_index().search(query, k)


def build_knowledge(settings):
    return LazyKnowledgeBase(settings) if settings.rag_enabled else None
