"""
`search_runbooks` — semantic search over a directory of markdown runbooks.

Uses Chroma (embedded) as the vector database and sentence-transformers for
local embeddings. Runs entirely offline — no embedding API cost.

Ingestion:
- Walk the runbook_dir on first use, split each markdown file into chunks,
  embed, and store. Persistence is on disk so repeat runs are fast.
- If files change on disk, the collection is rebuilt (very cheap for a few
  dozen runbooks).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

COLLECTION_NAME = "runbooks"


def _split_markdown(text: str, chunk_size: int = 800) -> list[str]:
    """Split markdown into roughly `chunk_size`-char chunks along paragraph
    boundaries. Simple, no external deps."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for p in paragraphs:
        if len(current) + len(p) + 2 <= chunk_size:
            current = f"{current}\n\n{p}" if current else p
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)
    return chunks or [text]


def _fingerprint_dir(runbook_dir: Path) -> str:
    """Hash the set of runbook (path, mtime, size) tuples. Used to decide
    whether to rebuild the collection."""
    h = hashlib.sha256()
    for md in sorted(runbook_dir.rglob("*.md")):
        st = md.stat()
        h.update(f"{md.name}:{st.st_mtime_ns}:{st.st_size}\n".encode())
    return h.hexdigest()


class RunbookTool:
    def __init__(self, runbook_dir: str, persist_dir: str, embeddings_model: str):
        self.runbook_dir = Path(runbook_dir)
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.embedder = SentenceTransformer(embeddings_model)
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = None
        self._current_fingerprint: str | None = None

    def _collection_up_to_date(self) -> bool:
        if not self.runbook_dir.exists():
            return True
        current = _fingerprint_dir(self.runbook_dir)
        return self._current_fingerprint == current

    def _rebuild(self) -> None:
        log.info("rebuilding_runbook_index dir=%s", self.runbook_dir)
        # Nuke and recreate collection so we don't accumulate stale chunks.
        try:
            self.client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self._collection = self.client.create_collection(COLLECTION_NAME)

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        for md_path in sorted(self.runbook_dir.rglob("*.md")):
            text = md_path.read_text(encoding="utf-8")
            chunks = _split_markdown(text)
            for idx, chunk in enumerate(chunks):
                ids.append(f"{md_path.name}::{idx}")
                documents.append(chunk)
                metadatas.append(
                    {"source": md_path.name, "chunk": idx}
                )

        if documents:
            embeddings = self.embedder.encode(documents).tolist()
            self._collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
        self._current_fingerprint = _fingerprint_dir(self.runbook_dir)
        log.info(
            "runbook_index_built runbooks=%d chunks=%d",
            len(list(self.runbook_dir.rglob("*.md"))),
            len(documents),
        )

    def _ensure_ready(self) -> None:
        if self._collection is None or not self._collection_up_to_date():
            self._rebuild()

    def run(self, query: str, top_k: int = 3) -> str:
        self._ensure_ready()
        if self._collection is None or not self.runbook_dir.exists():
            return json.dumps({"result": "no_runbooks_indexed"})

        try:
            query_emb = self.embedder.encode([query]).tolist()
            hits = self._collection.query(
                query_embeddings=query_emb,
                n_results=top_k,
            )
        except Exception as exc:
            return json.dumps({"error": f"runbook_query_error: {exc}"})

        docs = hits.get("documents", [[]])[0]
        metas = hits.get("metadatas", [[]])[0]
        results = [
            {
                "source": meta.get("source"),
                "chunk": meta.get("chunk"),
                "excerpt": doc[:600],
            }
            for doc, meta in zip(docs, metas)
        ]
        return json.dumps({"query": query, "results": results}, indent=2)
