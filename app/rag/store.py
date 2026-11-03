"""Vector store: a persistent local Chroma collection.

To move to Postgres + pgvector, implement the same three methods (`upsert`, `delete_missing`,
`query`) over a table `chunks(id text primary key, source text, heading text, text text,
embedding vector(N))` with `ORDER BY embedding <=> $1 LIMIT k`; nothing else changes.
"""

from pathlib import Path

from app.rag.chunking import Chunk


class ChromaStore:
    def __init__(self, path: str | Path, collection: str):
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.client = chromadb.PersistentClient(
            path=str(path), settings=ChromaSettings(anonymized_telemetry=False)
        )
        # Embeddings are always supplied explicitly, so Chroma never downloads its default model.
        self.collection = self.client.get_or_create_collection(
            collection, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )

    def count(self) -> int:
        return self.collection.count()

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        self.collection.upsert(
            ids=[c.id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=embeddings,
            metadatas=[{"source": c.source, "heading": c.heading} for c in chunks],
        )

    def delete_missing(self, keep: set[str]) -> int:
        existing = set(self.collection.get(include=[])["ids"])
        stale = sorted(existing - keep)
        if stale:
            self.collection.delete(ids=stale)
        return len(stale)

    def query(self, embedding: list[float], k: int) -> list[dict]:
        if self.count() == 0:
            return []
        result = self.collection.query(query_embeddings=[embedding], n_results=min(k, self.count()))
        return [
            {
                "id": identifier,
                "text": text,
                "source": metadata["source"],
                "heading": metadata["heading"],
                "score": round(1 - distance, 4),
            }
            for identifier, text, metadata, distance in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
                strict=True,
            )
        ]
