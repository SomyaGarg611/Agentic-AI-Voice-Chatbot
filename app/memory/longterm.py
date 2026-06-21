import asyncio
import hashlib
import json
from typing import List, Optional
import aiosqlite

DB_PATH = "memory.db"
_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        await _db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await _db.execute("""
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_text TEXT NOT NULL,
                agent_text TEXT NOT NULL,
                summary TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await _db.commit()
    return _db


async def store_turn(session_id: str, user_text: str, agent_text: str):
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO sessions (id) VALUES (?)", (session_id,)
    )
    summary = f"User asked: {user_text[:200]}. Agent said: {agent_text[:300]}"
    await db.execute(
        "INSERT INTO turns (session_id, user_text, agent_text, summary) VALUES (?, ?, ?, ?)",
        (session_id, user_text, agent_text, summary),
    )
    await db.commit()

    # Store in ChromaDB for semantic retrieval
    try:
        from app.rag.store import get_store
        store = get_store()
        chunk_id = hashlib.md5(f"mem:{session_id}:{user_text[:50]}".encode()).hexdigest()
        store.add_documents(
            [summary],
            [{"source": f"memory:{session_id}", "type": "conversation"}],
            [chunk_id],
        )
    except Exception:
        pass


async def retrieve_relevant(query: str, top_k: int = 3) -> List[str]:
    try:
        from app.rag.store import get_store
        store = get_store()
        results = store.query(query, top_k=top_k * 2)
        memories = [
            r["content"] for r in results
            if r.get("source", "").startswith("memory:") and r.get("relevance", 0) > 0.5
        ]
        return memories[:top_k]
    except Exception:
        return []


async def get_recent_turns(session_id: str, limit: int = 5) -> List[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT user_text, agent_text FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"user": r[0], "agent": r[1]} for r in reversed(rows)]
