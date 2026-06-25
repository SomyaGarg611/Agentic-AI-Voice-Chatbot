import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.rag.ingest import ingest_bytes
from app.rag.store import get_store
from app.memory.longterm import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

os.makedirs("uploads", exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-init persistent stores
    await get_db()
    get_store()
    logger.info("VoiceBot ready — Claude: %s | Deepgram: %s | ElevenLabs: %s | Tavily: %s | Langfuse: %s",
                settings.claude_model,
                "✓" if settings.has_deepgram else "✗",
                "✓" if settings.has_elevenlabs else "✗",
                "✓" if settings.has_tavily else "✗",
                "✓" if settings.has_langfuse else "✗")
    yield


app = FastAPI(title="VoiceBot — Agentic AI Research Analyst", lifespan=lifespan)


# ── WebSocket voice endpoint ────────────────────────────────────────────────

@app.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket):
    from app.voice.session import VoiceSession
    await websocket.accept()
    session = VoiceSession(websocket)
    await session.run()


# ── RAG document upload ─────────────────────────────────────────────────────

@app.post("/api/ingest")
async def ingest_document(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    try:
        n_chunks = ingest_bytes(data, file.filename or "upload")
        return {"filename": file.filename, "chunks_indexed": n_chunks}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/rag/stats")
async def rag_stats():
    return {"doc_chunks": get_store().count()}


# ── Chat history ──────────────────────────────────────────────────────────────

@app.get("/api/chats")
async def list_chats_endpoint():
    from app.memory.longterm import list_chats
    return {"chats": await list_chats()}


@app.get("/api/chats/{session_id}")
async def get_chat_endpoint(session_id: str):
    from app.memory.longterm import get_chat_messages
    return {"messages": await get_chat_messages(session_id)}


@app.delete("/api/chats/{session_id}")
async def delete_chat_endpoint(session_id: str):
    from app.memory.longterm import delete_chat
    await delete_chat(session_id)
    return {"deleted": session_id}


# ── Health check ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "model": settings.claude_model,
        "deepgram": settings.has_deepgram,
        "elevenlabs": settings.has_elevenlabs,
        "tavily": settings.has_tavily,
        "langfuse": settings.has_langfuse,
    }


# ── Static web frontend ─────────────────────────────────────────────────────
# Serve the built React app (frontend/dist) when present; fall back to the
# legacy vanilla UI in web/ otherwise.
_FRONTEND_DIR = "frontend/dist" if os.path.isdir("frontend/dist") else "web"
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="web")
