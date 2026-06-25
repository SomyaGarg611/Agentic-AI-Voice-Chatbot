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


# ── Chat management (multi-conversation history) ────────────────────────────

async def list_chats() -> List[dict]:
    """All chats that have at least one turn, most recently active first."""
    db = await get_db()
    async with db.execute("""
        SELECT s.id,
               (SELECT user_text FROM turns t1 WHERE t1.session_id = s.id ORDER BY t1.id ASC LIMIT 1),
               (SELECT MAX(created_at) FROM turns t2 WHERE t2.session_id = s.id),
               (SELECT COUNT(*) FROM turns t3 WHERE t3.session_id = s.id)
        FROM sessions s
        WHERE EXISTS (SELECT 1 FROM turns t WHERE t.session_id = s.id)
        ORDER BY 3 DESC
    """) as cursor:
        rows = await cursor.fetchall()
    chats = []
    for sid, title, updated_at, count in rows:
        t = (title or "New chat").strip()
        chats.append({
            "id": sid,
            "title": (t[:48] + "…") if len(t) > 48 else t,
            "updated_at": updated_at,
            "turns": count,
        })
    return chats


async def get_chat_messages(session_id: str) -> List[dict]:
    """Full message list for the UI when opening a past chat."""
    db = await get_db()
    async with db.execute(
        "SELECT user_text, agent_text FROM turns WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    messages = []
    for user_text, agent_text in rows:
        messages.append({"role": "user", "text": user_text})
        messages.append({"role": "agent", "text": agent_text})
    return messages


async def load_history(session_id: str, max_turns: int = 10) -> list:
    """Rebuild the agent's conversation_history (role/content) from stored turns."""
    db = await get_db()
    async with db.execute(
        "SELECT user_text, agent_text FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, max_turns),
    ) as cursor:
        rows = await cursor.fetchall()
    history = []
    for user_text, agent_text in reversed(rows):
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": agent_text})
    return history


async def delete_chat(session_id: str):
    db = await get_db()
    await db.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
    await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await db.commit()
    # Best-effort: drop this chat's semantic memories from ChromaDB too
    try:
        from app.rag.store import get_store
        get_store()._col.delete(where={"source": f"memory:{session_id}"})
    except Exception:
        pass
