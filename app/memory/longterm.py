import hashlib
from typing import List, Optional
import aiosqlite

DB_PATH = "memory.db"
_db: Optional[aiosqlite.Connection] = None


async def _ensure_column(db, table: str, column: str, decl: str):
    """Add a column if the table doesn't already have it (simple migration)."""
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        cols = [r[1] for r in await cur.fetchall()]
    if column not in cols:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        await _db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await _db.execute("""
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id TEXT,
                user_text TEXT NOT NULL,
                agent_text TEXT NOT NULL,
                summary TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migrate older DBs that predate per-user scoping
        await _ensure_column(_db, "sessions", "user_id", "TEXT")
        await _ensure_column(_db, "turns", "user_id", "TEXT")
        await _db.commit()
    return _db


async def store_turn(user_id: str, session_id: str, user_text: str, agent_text: str):
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO sessions (id, user_id) VALUES (?, ?)", (session_id, user_id)
    )
    summary = f"User asked: {user_text[:200]}. Agent said: {agent_text[:300]}"
    await db.execute(
        "INSERT INTO turns (session_id, user_id, user_text, agent_text, summary) VALUES (?, ?, ?, ?, ?)",
        (session_id, user_id, user_text, agent_text, summary),
    )
    await db.commit()

    # Semantic memory in ChromaDB, tagged with the user so recall is per-user
    try:
        from app.rag.store import get_store
        store = get_store()
        chunk_id = hashlib.md5(f"mem:{session_id}:{user_text[:50]}".encode()).hexdigest()
        store.add_documents(
            [summary],
            [{"source": f"memory:{session_id}", "type": "conversation", "user_id": user_id or ""}],
            [chunk_id],
        )
    except Exception:
        pass


async def retrieve_relevant(query: str, user_id: str, top_k: int = 3) -> List[str]:
    try:
        from app.rag.store import get_store
        store = get_store()
        results = store.query(query, top_k=top_k * 3)
        memories = [
            r["content"] for r in results
            if r.get("source", "").startswith("memory:")
            and r.get("relevance", 0) > 0.5
            and r.get("user_id", "") == (user_id or "")
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


# ── Chat management (multi-conversation history, scoped per user) ───────────

async def list_chats(user_id: str) -> List[dict]:
    db = await get_db()
    async with db.execute("""
        SELECT s.id,
               (SELECT user_text FROM turns t1 WHERE t1.session_id = s.id ORDER BY t1.id ASC LIMIT 1),
               (SELECT MAX(created_at) FROM turns t2 WHERE t2.session_id = s.id),
               (SELECT COUNT(*) FROM turns t3 WHERE t3.session_id = s.id)
        FROM sessions s
        WHERE s.user_id = ? AND EXISTS (SELECT 1 FROM turns t WHERE t.session_id = s.id)
        ORDER BY 3 DESC
    """, (user_id,)) as cursor:
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


async def get_chat_messages(session_id: str, user_id: str) -> List[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT user_text, agent_text FROM turns WHERE session_id = ? AND user_id = ? ORDER BY id ASC",
        (session_id, user_id),
    ) as cursor:
        rows = await cursor.fetchall()
    messages = []
    for user_text, agent_text in rows:
        messages.append({"role": "user", "text": user_text})
        messages.append({"role": "agent", "text": agent_text})
    return messages


async def load_history(session_id: str, user_id: str, max_turns: int = 10) -> list:
    db = await get_db()
    async with db.execute(
        "SELECT user_text, agent_text FROM turns WHERE session_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, user_id, max_turns),
    ) as cursor:
        rows = await cursor.fetchall()
    history = []
    for user_text, agent_text in reversed(rows):
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": agent_text})
    return history


async def delete_chat(session_id: str, user_id: str):
    db = await get_db()
    await db.execute("DELETE FROM turns WHERE session_id = ? AND user_id = ?", (session_id, user_id))
    await db.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
    await db.commit()
    try:
        from app.rag.store import get_store
        get_store()._col.delete(where={"source": f"memory:{session_id}"})
    except Exception:
        pass
