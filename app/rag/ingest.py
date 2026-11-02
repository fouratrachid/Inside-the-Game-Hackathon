"""Ingest `knowledge/*.md` into the vector store: `pipenv run python -m app.rag.ingest`.

Idempotent: chunk ids are content hashes, so re-running upserts the same ids and deletes
chunks whose text no longer exists.
"""

from pathlib import Path

from app.config import Settings
from app.rag.chunking import load_corpus
from app.rag.embeddings import Embedder, build_embedder
from app.rag.knowledge import collection_name
from app.rag.store import ChromaStore

ROOT = Path(__file__).resolve().parents[2]


def ingest(store, embedder: Embedder, folder: Path = ROOT / "knowledge") -> dict:
    chunks = load_corpus(folder)
    store.upsert(chunks, embedder.embed_documents([c.text for c in chunks]))
    removed = store.delete_missing({c.id for c in chunks})
    return {
        "chunks": len(chunks),
        "sources": len({c.source for c in chunks}),
        "removed": removed,
        "total": store.count(),
        "embedder": embedder.name,
    }


def main() -> None:
    settings = Settings()
    store = ChromaStore(settings.rag_path, collection_name(settings))
    print(ingest(store, build_embedder(settings)))


if __name__ == "__main__":
    main()
