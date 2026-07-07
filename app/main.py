import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, WebSocket, HTTPException, Depends, Request, Body
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.rag.ingest import ingest_bytes
from app.rag.store import get_store
from app.memory.longterm import get_db
from app.security import (
    current_user, allow, issue_session_jwt, verify_google_id_token,
)

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

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/api/auth/google")
async def auth_google(id_token: str = Body(..., embed=True)):
    user = verify_google_id_token(id_token)
    if not user:
        raise HTTPException(status_code=401, detail="Google sign-in failed")
    return {"token": issue_session_jwt(user), "user": user}


@app.post("/api/auth/dev")
async def auth_dev(email: str = Body(..., embed=True)):
    """Dev-only login used when Google isn't configured — never enabled if it is."""
    if settings.has_google:
        raise HTTPException(status_code=404, detail="Not available")
    email = email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email")
    user = {"sub": f"dev:{email}", "email": email, "name": email.split("@")[0], "picture": ""}
    return {"token": issue_session_jwt(user), "user": user}


# ── WebSocket voice endpoint ────────────────────────────────────────────────

@app.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket):
    from app.voice.session import VoiceSession
    from app.security import user_from_token
    await websocket.accept()
    user = user_from_token(websocket.query_params.get("token"))
    if not user:
        await websocket.close(code=1008)  # not authenticated
        return
    session = VoiceSession(websocket, user_id=user["sub"])
    await session.run()


# ── RAG document upload ─────────────────────────────────────────────────────

@app.post("/api/ingest")
async def ingest_document(request: Request, file: UploadFile = File(...), user: dict = Depends(current_user)):
    if not allow(f"ingest:{user['sub']}", settings.max_uploads_per_min):
        raise HTTPException(status_code=429, detail="Too many uploads — slow down")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    try:
        n_chunks = ingest_bytes(data, file.filename or "upload")
        return {"filename": file.filename, "chunks_indexed": n_chunks}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/rag/stats")
async def rag_stats(user: dict = Depends(current_user)):
    return {"doc_chunks": get_store().count()}


# ── Chat history (scoped to the signed-in user) ─────────────────────────────────

@app.get("/api/chats")
async def list_chats_endpoint(user: dict = Depends(current_user)):
    from app.memory.longterm import list_chats
    return {"chats": await list_chats(user["sub"])}


@app.get("/api/chats/{session_id}")
async def get_chat_endpoint(session_id: str, user: dict = Depends(current_user)):
    from app.memory.longterm import get_chat_messages
    return {"messages": await get_chat_messages(session_id, user["sub"])}


@app.delete("/api/chats/{session_id}")
async def delete_chat_endpoint(session_id: str, user: dict = Depends(current_user)):
    from app.memory.longterm import delete_chat
    await delete_chat(session_id, user["sub"])
    return {"deleted": session_id}


# ── Public config + health ────────────────────────────────────────────────────

@app.get("/api/config")
async def public_config():
    """Unauthenticated — tells the frontend which sign-in method to show."""
    return {
        "google_client_id": settings.google_client_id or "",
        "dev_login": not settings.has_google,
    }


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
