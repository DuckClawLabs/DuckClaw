"""
DuckClaw Memory System.
Two-layer storage:
  1. SQLite — structured facts (user preferences, key info)
  2. ChromaDB — semantic vector search over conversation history
"""

import os
import json
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


FACTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fact        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'general',
    confidence  REAL NOT NULL DEFAULT 1.0,
    source_msg  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);
CREATE INDEX IF NOT EXISTS idx_facts_created ON facts(created_at DESC);
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
        self._db.executescript(FACTS_SCHEMA)
        self._db.executescript(CONVERSATIONS_SCHEMA)
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
            logger.info("ChromaDB initialized for semantic memory")
        except Exception as e:
            logger.warning(f"ChromaDB unavailable ({e}). Falling back to SQLite-only search.")
            self._chroma = None
            self._collection = None

        logger.info(f"Memory store initialized at {db_path}")

    # ─── Facts ────────────────────────────────────────────────────────────────

    def save_fact(
        self,
        fact: str,
        category: str = "general",
        confidence: float = 1.0,
        source_msg: Optional[str] = None,
    ) -> int:
        """Store a structured fact about the user. Returns fact ID."""
        cursor = self._db.execute(
            "INSERT INTO facts (fact, category, confidence, source_msg) VALUES (?, ?, ?, ?)",
            (fact, category, confidence, source_msg),
        )
        self._db.commit()
        return cursor.lastrowid

    def list_facts(self, category: Optional[str] = None, limit: int = 100) -> list[dict]:
        """List stored facts, optionally filtered by category."""
        if category:
            rows = self._db.execute(
                "SELECT * FROM facts WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM facts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_fact(self, fact_id: int) -> bool:
        """User can delete any fact from the dashboard."""
        cursor = self._db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        self._db.commit()
        return cursor.rowcount > 0

    def update_fact(self, fact_id: int, new_text: str) -> bool:
        """Update an existing fact."""
        cursor = self._db.execute(
            "UPDATE facts SET fact = ?, updated_at = datetime('now') WHERE id = ?",
            (new_text, fact_id),
        )
        self._db.commit()
        return cursor.rowcount > 0

    def get_facts_summary(self) -> str:
        """Build a compact facts summary for injecting into LLM context."""
        facts = self.list_facts(limit=50)
        if not facts:
            return ""

        by_category: dict[str, list[str]] = {}
        for f in facts:
            cat = f["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f["fact"])

        lines = ["## What I know about you:"]
        for cat, items in by_category.items():
            lines.append(f"\n**{cat.capitalize()}:**")
            for item in items[:10]:  # Cap per category
                lines.append(f"- {item}")

        return "\n".join(lines)

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
            "SELECT role, content, created_at FROM conversations "
            "WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        # Return in chronological order for LLM
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

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

    def get_all_sessions(self) -> list[dict]:
        """List all conversation sessions (for dashboard)."""
        rows = self._db.execute(
            "SELECT session_id, source, COUNT(*) as msg_count, MAX(created_at) as last_active "
            "FROM conversations GROUP BY session_id ORDER BY last_active DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Memory stats for dashboard."""
        fact_count = self._db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        msg_count = self._db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        session_count = self._db.execute(
            "SELECT COUNT(DISTINCT session_id) FROM conversations"
        ).fetchone()[0]

        chroma_count = 0
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
