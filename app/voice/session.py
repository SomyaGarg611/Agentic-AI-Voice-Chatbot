import asyncio
import contextlib
import json
import logging
import uuid
from typing import Optional

from fastapi import WebSocket

from app.config import settings
from app.agent.loop import run_agent_streaming
from app.voice.deepgram_stt import DeepgramSTT
from app.voice.elevenlabs_tts import synthesize_sentence, clean_for_tts
from app.memory.longterm import store_turn, retrieve_relevant, get_recent_turns, load_history
from app.observability.tracing import flush
from app.security import allow

logger = logging.getLogger(__name__)


class VoiceSession:
    def __init__(self, ws: WebSocket, user_id: str = "anon"):
        self.ws = ws
        self.user_id = user_id
        self.session_id = str(uuid.uuid4())
        self.processing = False
        self.conversation_history: list = []
        self._stt: Optional[DeepgramSTT] = None
        self._turn_task: Optional[asyncio.Task] = None   # the current agent+TTS task
        self._client_ip = ws.client.host if ws.client else "unknown"

    async def run(self):
        await self.ws.send_json({"type": "connected", "session_id": self.session_id})

        if settings.has_deepgram:
            self._stt = DeepgramSTT(on_interim=self._on_interim, on_final=self._on_final)
            ok = await self._stt.start()
            if ok:
                await self.ws.send_json({"type": "stt_ready", "provider": "deepgram"})
            else:
                self._stt = None
                await self.ws.send_json({"type": "stt_ready", "provider": "browser"})
        else:
            await self.ws.send_json({"type": "stt_ready", "provider": "browser"})

        _audio_frames = 0
        try:
            while True:
                frame = await self.ws.receive()
                if frame["type"] == "websocket.disconnect":
                    break
                if frame.get("bytes"):
                    _audio_frames += 1
                    if _audio_frames == 1:
                        logger.info("First audio frame received (%d bytes)", len(frame["bytes"]))
                    elif _audio_frames % 200 == 0:
                        logger.info("Audio flowing: %d frames", _audio_frames)
                    # Only forward audio while not in the middle of a turn
                    if not self.processing and self._stt:
                        await self._stt.send(frame["bytes"])
                elif frame.get("text"):
                    with contextlib.suppress(Exception):
                        await self._handle_text_msg(json.loads(frame["text"]))
        except Exception as exc:
            logger.debug("Session ended: %s", exc)
        finally:
            if self._turn_task and not self._turn_task.done():
                self._turn_task.cancel()
            if self._stt:
                await self._stt.close()
            flush()

    # ── STT callbacks ────────────────────────────────────────────────────

    async def _on_interim(self, text: str):
        await self.ws.send_json({"type": "transcript", "text": text, "is_final": False})

    async def _on_final(self, text: str):
        await self.ws.send_json({"type": "transcript", "text": text, "is_final": True})
        if text.strip():
            await self._start_turn(text)

    # ── Text message handler ─────────────────────────────────────────────

    async def _handle_text_msg(self, msg: dict):
        kind = msg.get("type", "")

        if kind == "session":
            # Client selects which chat to use (new or resumed from history)
            new_id = msg.get("session_id")
            if new_id:
                # Cancel anything in flight on the old chat
                if self._turn_task and not self._turn_task.done():
                    self._turn_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._turn_task
                self.processing = False
                self.session_id = new_id
                self.conversation_history = await load_history(new_id, self.user_id)
                logger.info("Switched to chat %s (%d prior messages)",
                            new_id, len(self.conversation_history))

        elif kind == "transcript":
            text = msg.get("text", "").strip()
            if text:
                await self._start_turn(text)

        elif kind == "audio_config":
            sr = int(msg.get("sample_rate", 16000))
            logger.info("Browser audio sample rate: %d Hz", sr)
            if self._stt:
                await self._stt.close()
            self._stt = DeepgramSTT(
                on_interim=self._on_interim,
                on_final=self._on_final,
                sample_rate=sr,
            )
            ok = await self._stt.start()
            logger.info("Deepgram restarted at %d Hz: %s", sr, ok)
            if not ok:
                self._stt = None

        elif kind == "stop":
            # User explicitly stopped the agent (stop button / Escape key)
            if self._turn_task and not self._turn_task.done():
                self._turn_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._turn_task
            self.processing = False

        elif kind == "ping":
            await self.ws.send_json({"type": "pong"})

    # ── Turn lifecycle ───────────────────────────────────────────────────

    async def _start_turn(self, user_text: str):
        """Cancel any in-flight turn (barge-in), then start a fresh one."""
        if not allow(f"turns:{self._client_ip}", settings.max_turns_per_min):
            with contextlib.suppress(Exception):
                await self.ws.send_json({"type": "error", "message": "Rate limit reached — please wait a moment."})
            return
        if self._turn_task and not self._turn_task.done():
            logger.info("Barge-in: cancelling current turn for new query")
            self._turn_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._turn_task
            # Tell the browser to stop playing whatever is mid-stream
            with contextlib.suppress(Exception):
                await self.ws.send_json({"type": "interrupt"})

        self.processing = True
        self._turn_task = asyncio.create_task(self._process_turn(user_text))

    async def _process_turn(self, user_text: str):
        try:
            await self.ws.send_json({"type": "agent_thinking"})

            memories = await retrieve_relevant(user_text, self.user_id)
            recent = await get_recent_turns(self.session_id, limit=3)

            memory_context = ""
            if memories:
                memory_context += "Relevant memories:\n" + "\n".join(f"- {m}" for m in memories)
            if recent:
                memory_context += "\n\nRecent turns:\n" + "\n".join(
                    f"User: {t['user']}\nAria: {t['agent']}" for t in recent
                )

            # Track whether ElevenLabs actually produced audio this turn.
            tts = {"bytes": 0, "started": False, "dead": False}

            async def on_tool(name: str):
                with contextlib.suppress(Exception):
                    await self.ws.send_json({"type": "tool_use", "tool": name})

            async def on_sentence(text: str):
                # Stream the sentence to the UI immediately…
                await self.ws.send_json({"type": "agent_delta", "text": text + " "})
                # …then synthesize its audio. Only emit audio_start/bytes if the TTS
                # call actually returns audio, so a quota/API failure cleanly falls
                # back to the browser voice instead of going silent.
                if settings.has_elevenlabs and not tts["dead"]:
                    spoken = clean_for_tts(text)
                    if spoken.strip():
                        audio = await synthesize_sentence(spoken)
                        if audio:
                            if not tts["started"]:
                                await self.ws.send_json({"type": "audio_start"})
                                tts["started"] = True
                            await self.ws.send_bytes(audio)
                            tts["bytes"] += len(audio)
                        else:
                            # First failure → stop retrying and tell the client once
                            tts["dead"] = True
                            with contextlib.suppress(Exception):
                                await self.ws.send_json({
                                    "type": "notice",
                                    "message": "Premium voice unavailable — using browser voice",
                                })

            response_text, updated_history = await run_agent_streaming(
                user_text,
                self.conversation_history,
                memory_context=memory_context,
                session_id=self.session_id,
                on_tool=on_tool,
                on_sentence=on_sentence,
            )

            self.conversation_history = updated_history[-20:]

            await self.ws.send_json({"type": "audio_end"})
            await self.ws.send_json({
                "type": "agent_done",
                "text": response_text,
                # Only claim audio if ElevenLabs actually delivered some — otherwise
                # the browser speaks the text via Web Speech API.
                "has_audio": tts["bytes"] > 0,
            })

            await store_turn(self.user_id, self.session_id, user_text, response_text)

        except asyncio.CancelledError:
            # Barge-in: clean up and let the new turn take over
            logger.info("Turn cancelled (barge-in)")
            with contextlib.suppress(Exception):
                await self.ws.send_json({"type": "audio_end"})
            raise

        except Exception as exc:
            logger.error("Turn error: %s", exc)
            with contextlib.suppress(Exception):
                await self.ws.send_json({"type": "error", "message": str(exc)})

        finally:
            self.processing = False
