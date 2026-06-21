import os
from typing import List, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings

_store: Optional["RagStore"] = None


def get_store() -> "RagStore":
    global _store
    if _store is None:
        _store = RagStore()
    return _store


class RagStore:
    COLLECTION = "voicebot_docs"

    def __init__(self):
        self._client = chromadb.PersistentClient(
            path="chroma_db",
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._col = self._client.get_or_create_collection(
            name=self.COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    def add_documents(self, chunks: List[str], metadatas: List[dict], ids: List[str]):
        if not chunks:
            return
        self._col.upsert(documents=chunks, metadatas=metadatas, ids=ids)

    def query(self, query: str, top_k: int = 4) -> List[dict]:
        if self._col.count() == 0:
            return []
        results = self._col.query(
            query_texts=[query],
            n_results=min(top_k, self._col.count()),
            include=["documents", "metadatas", "distances"],
        )
        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            output.append({
                "content": doc,
                "source": meta.get("source", "unknown"),
                "relevance": round(1 - dist, 3),
            })
        return output

    def count(self) -> int:
        return self._col.count()
