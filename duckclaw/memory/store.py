"""
DuckClaw Memory System.
Two-layer storage:
  1. SQLite — conversation history + ingested file records
  2. ChromaDB — facts (semantic search) + conversation vectors + ingested doc chunks
"""

import os
import json
import uuid
import asyncio
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings

from duckclaw.core.config import MemoryConfig

logger = logging.getLogger(__name__)


INGESTED_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingested_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ingested_at ON ingested_files(ingested_at DESC);
"""


CONVERSATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    source      TEXT DEFAULT 'terminal',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conv_created ON conversations(created_at DESC);
"""


class MemoryStore:
    """
    Persistent memory for DuckClaw.

    Facts: structured key facts about the user stored in SQLite.
    Conversations: full history stored in SQLite + embedded in ChromaDB for semantic search.

    Usage:
        store = MemoryStore(config.memory)
        await store.initialize()
        store.save_fact("User works at Acme Corp", category="work")
        results = store.search_memory("Where does user work?")
    """

    def __init__(self, config: MemoryConfig):
        self.config = config
        self._db: Optional[sqlite3.Connection] = None
        self._chroma: Optional[chromadb.ClientAPI] = None
        self._collection = None
        self._ingested_collection = None
        self._facts_collection = None
        self._skills_collection = None

    async def initialize(self):
        """Initialize databases. Call once at startup."""
        # Ensure directories exist
        db_path = self.config.db_path_expanded
        chroma_path = self.config.chroma_path_expanded

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(chroma_path).mkdir(parents=True, exist_ok=True)

        # SQLite
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(CONVERSATIONS_SCHEMA)
        self._db.executescript(INGESTED_SCHEMA)
        self._db.commit()

        # ChromaDB (embedded — no server needed)
        try:
            self._chroma = chromadb.PersistentClient(
                path=chroma_path,
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._chroma.get_or_create_collection(
                name="duckclaw_conversations",
                metadata={"hnsw:space": "cosine"},
            )
            self._ingested_collection = self._chroma.get_or_create_collection(
                name="duckclaw_ingested",
                metadata={"hnsw:space": "cosine"},
            )
            self._facts_collection = self._chroma.get_or_create_collection(
                name="duckclaw_facts",
                metadata={"hnsw:space": "cosine"},
            )
            self._skills_collection = self._chroma.get_or_create_collection(
                name="duckclaw_skills",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("ChromaDB initialized for semantic memory")
        except Exception as e:
            logger.warning(f"ChromaDB unavailable ({e}). Falling back to SQLite-only search.")
            self._chroma = None
            self._collection = None

        logger.info(f"Memory store initialized at {db_path}")

    # ─── Facts (ChromaDB only) ────────────────────────────────────────────────

    def save_fact(
        self,
        fact: str,
        category: str = "general",
        confidence: float = 1.0,
        source_msg: Optional[str] = None,
    ) -> str:
        """Store a fact in ChromaDB. Returns the fact ID (string)."""
        if self._facts_collection is None:
            raise RuntimeError("ChromaDB unavailable — cannot store facts")
        fact_id = f"fact_{uuid.uuid4().hex}"
        self._facts_collection.add(
            ids=[fact_id],
            documents=[fact],
            metadatas=[{
                "category": category,
                "confidence": confidence,
                "source_msg": source_msg or "",
                "created_at": datetime.now().isoformat(),
            }],
        )
        return fact_id

    def list_facts(self, category: Optional[str] = None, limit: int = 100) -> list[dict]:
        """List facts from ChromaDB, optionally filtered by category."""
        if self._facts_collection is None:
            return []
        try:
            kwargs = {"where": {"category": category}} if category else {}
            result = self._facts_collection.get(**kwargs)
            rows = [
                {
                    "id": id_,
                    "fact": doc,
                    "category": meta.get("category", "general"),
                    "confidence": meta.get("confidence", 1.0),
                    "source_msg": meta.get("source_msg", ""),
                    "created_at": meta.get("created_at", ""),
                }
                for id_, doc, meta in zip(result["ids"], result["documents"], result["metadatas"])
            ]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return rows[:limit]
        except Exception as e:
            logger.warning(f"ChromaDB list_facts failed: {e}")
            return []

    def delete_fact(self, fact_id: str) -> bool:
        """Delete a fact from ChromaDB by ID."""
        if self._facts_collection is None:
            return False
        try:
            self._facts_collection.delete(ids=[fact_id])
            return True
        except Exception as e:
            logger.warning(f"ChromaDB fact delete failed: {e}")
            return False

    def update_fact(self, fact_id: str, new_text: str) -> bool:
        """Update fact text in ChromaDB (preserves metadata)."""
        if self._facts_collection is None:
            return False
        try:
            existing = self._facts_collection.get(ids=[fact_id])
            if not existing["ids"]:
                return False
            meta = {**existing["metadatas"][0], "updated_at": datetime.now().isoformat()}
            self._facts_collection.delete(ids=[fact_id])
            self._facts_collection.add(ids=[fact_id], documents=[new_text], metadatas=[meta])
            return True
        except Exception as e:
            logger.warning(f"ChromaDB fact update failed: {e}")
            return False

    def search_facts(self, query: str, n_results: int = 10) -> list[dict]:
        """Semantic search over facts — returns only facts relevant to the query."""
        if self._facts_collection is None:
            return []
        try:
            count = self._facts_collection.count()
            if count == 0:
                return []
            results = self._facts_collection.query(
                query_texts=[query],
                n_results=min(n_results, count),
            )
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            return [
                {
                    "fact": doc,
                    "category": meta.get("category", "general"),
                    "confidence": meta.get("confidence", 1.0),
                }
                for doc, meta in zip(docs, metas)
            ]
        except Exception as e:
            logger.warning(f"ChromaDB fact search failed: {e}")
            return []

    # ─── Skills Knowledge Base ────────────────────────────────────────────────

    def seed_skills(self, skills: list[dict]) -> None:
        """Populate the skills ChromaDB collection from a list of skill dicts. Idempotent."""
        if self._skills_collection is None:
            return
        existing = self._skills_collection.get()
        if existing["ids"]:
            self._skills_collection.delete(ids=existing["ids"])

        ids, documents, metadatas = [], [], []
        for skill in skills:
            search_doc = skill["description"]
            if skill.get("use_cases"):
                search_doc += "\nExample queries: " + "; ".join(skill["use_cases"])
            ids.append(skill["skill_id"])
            documents.append(search_doc)
            metadatas.append({
                "skill_id": skill["skill_id"],
                "name": skill["name"],
                "input_format": skill.get("input_format", ""),
                "output_format": skill.get("output_format", ""),
            })

        self._skills_collection.add(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(f"Seeded {len(skills)} skills into ChromaDB")

    def search_skills(self, query: str, n_results: int = 1, threshold: float = 0.1) -> list[dict]:
        """
        Semantic search over the skills knowledge base.
        Returns skills whose description/use-case matches the query.
        Each result includes: skill_id, name, description, input_format, output_format.
        Only returns results above the similarity threshold.
        """
        if self._skills_collection is None:
            return []
        try:
            count = self._skills_collection.count()
            if count == 0:
                return []
            results = self._skills_collection.query(
                query_texts=[query],
                n_results=min(n_results, count),
                include=["documents", "metadatas", "distances"],
            )
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            matched = []
            for doc, meta, dist in zip(docs, metas, distances):
                # ChromaDB cosine distance: 0 = identical, 2 = opposite; similarity = 1 - dist
                similarity = 1.0 - dist
                if similarity >= threshold:
                    matched.append({
                        "skill_id": meta.get("skill_id", ""),
                        "name": meta.get("name", ""),
                        "description": doc,
                        "input_format": meta.get("input_format", ""),
                        "output_format": meta.get("output_format", ""),
                        "similarity": round(similarity, 3),
                    })
            return matched
        except Exception as e:
            logger.warning(f"ChromaDB skill search failed: {e}")
            return []

    # ─── Knowledge Base (user-ingested documents) ─────────────────────────────

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
        chunks = []
        start = 0
        while start < len(text):
            chunks.append(text[start:start + chunk_size])
            start += chunk_size - overlap
        return chunks or [text]

    def ingest_document(self, filename: str, content: str, size_bytes: int) -> int:
        """Chunk text and store in ChromaDB ingested collection. Returns chunk count."""
        if self._ingested_collection is None:
            raise RuntimeError("ChromaDB unavailable — cannot ingest documents")
        chunks = self._chunk_text(content)
        ts = datetime.now().isoformat()
        ids, docs, metas = [], [], []
        for i, chunk in enumerate(chunks):
            ids.append(f"ingest_{filename}_{ts}_{i}")
            docs.append(chunk)
            metas.append({"filename": filename, "chunk_index": i, "ingested_at": ts})
        self._ingested_collection.add(ids=ids, documents=docs, metadatas=metas)
        self._db.execute(
            "INSERT INTO ingested_files (filename, size_bytes, chunk_count) VALUES (?, ?, ?)",
            (filename, size_bytes, len(chunks)),
        )
        self._db.commit()
        return len(chunks)

    def list_ingested_files(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM ingested_files ORDER BY ingested_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_ingested_file(self, file_id: int) -> bool:
        row = self._db.execute(
            "SELECT filename FROM ingested_files WHERE id = ?", (file_id,)
        ).fetchone()
        if not row:
            return False
        filename = row["filename"]
        if self._ingested_collection is not None:
            try:
                self._ingested_collection.delete(where={"filename": filename})
            except Exception as e:
                logger.warning(f"ChromaDB delete failed for {filename}: {e}")
        self._db.execute("DELETE FROM ingested_files WHERE id = ?", (file_id,))
        self._db.commit()
        return True

    # ─── Conversations ────────────────────────────────────────────────────────

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        source: str = "terminal",
    ) -> int:
        """Save a conversation message to history."""
        cursor = self._db.execute(
            "INSERT INTO conversations (session_id, role, content, source) VALUES (?, ?, ?, ?)",
            (session_id, role, content, source),
        )
        self._db.commit()
        msg_id = cursor.lastrowid

        # Also index in ChromaDB for semantic search
        if self._collection is not None and role == "user":
            try:
                self._collection.add(
                    ids=[f"msg_{msg_id}"],
                    documents=[content],
                    metadatas=[{
                        "session_id": session_id,
                        "role": role,
                        "source": source,
                        "timestamp": datetime.now().isoformat(),
                    }],
                )
            except Exception as e:
                logger.warning(f"Failed to index message in ChromaDB: {e}")

        return msg_id

    def get_session_history(self, session_id: str, limit: int = 20) -> list[dict]:
        """Get recent messages for a session (for LLM context window)."""
        rows = self._db.execute(
            "SELECT role, content FROM conversations "
            "WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        # Return in chronological order for LLM
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def search_memory(self, query: str, n_results: int = None) -> list[str]:
        """
        Semantic search over conversation history via ChromaDB.
        Falls back to SQLite keyword search if ChromaDB is unavailable.
        """
        n = n_results or self.config.semantic_search_results

        if self._collection is not None:
            try:
                results = self._collection.query(
                    query_texts=[query],
                    n_results=min(n, self._collection.count() or 1),
                )
                docs = results.get("documents", [[]])[0]
                return docs
            except Exception as e:
                logger.warning(f"ChromaDB search failed: {e}")

        # Fallback: SQLite LIKE search
        query_lower = f"%{query.lower()}%"
        rows = self._db.execute(
            "SELECT content FROM conversations WHERE lower(content) LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (query_lower, n),
        ).fetchall()
        return [r["content"] for r in rows]

    def list_conversations(
        self,
        session_id: Optional[str] = None,
        role: Optional[str] = None,
        source: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """List conversation rows with optional filters."""
        conditions = []
        params: list = []
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if role:
            conditions.append("role = ?")
            params.append(role)
        if source:
            conditions.append("source = ?")
            params.append(source)
        if q:
            conditions.append("lower(content) LIKE ?")
            params.append(f"%{q.lower()}%")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        rows = self._db.execute(
            f"SELECT * FROM conversations {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_sessions(self) -> list[dict]:
        """List all conversation sessions (for dashboard)."""
        rows = self._db.execute(
            "SELECT session_id, source, COUNT(*) as msg_count, MAX(created_at) as last_active "
            "FROM conversations GROUP BY session_id ORDER BY last_active DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Memory stats for dashboard."""
        msg_count = self._db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        session_count = self._db.execute(
            "SELECT COUNT(DISTINCT session_id) FROM conversations"
        ).fetchone()[0]

        fact_count = 0
        chroma_count = 0
        if self._facts_collection is not None:
            try:
                fact_count = self._facts_collection.count()
            except Exception:
                pass
        if self._collection is not None:
            try:
                chroma_count = self._collection.count()
            except Exception:
                pass

        return {
            "total_facts": fact_count,
            "total_messages": msg_count,
            "total_sessions": session_count,
            "semantic_index_size": chroma_count,
        }

    def close(self):
        """Close database connections."""
        if self._db:
            self._db.close()
