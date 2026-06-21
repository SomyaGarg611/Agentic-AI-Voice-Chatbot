import asyncio
import logging
from typing import Callable, Awaitable, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class DeepgramSTT:
    """Streams PCM-16 audio to Deepgram and emits transcripts via callbacks."""

    def __init__(
        self,
        on_interim: Callable[[str], Awaitable[None]],
        on_final: Callable[[str], Awaitable[None]],
        sample_rate: int = 16000,
    ):
        self._on_interim = on_interim
        self._on_final = on_final
        self._sample_rate = sample_rate
        self._conn = None

    async def start(self) -> bool:
        if not settings.has_deepgram:
            return False
        try:
            from deepgram import (
                DeepgramClient,
                LiveTranscriptionEvents,
                LiveOptions,
            )

            client = DeepgramClient(settings.deepgram_api_key)
            self._conn = client.listen.asyncwebsocket.v("1")

            on_interim = self._on_interim
            on_final = self._on_final

            async def _on_transcript(dg_self, result, **kwargs):
                try:
                    alt = result.channel.alternatives[0]
                    text = alt.transcript
                    logger.info("Deepgram transcript: %r (final=%s)", text, result.is_final)
                    if not text.strip():
                        return
                    if result.is_final:
                        await on_final(text)
                    else:
                        await on_interim(text)
                except Exception as exc:
                    logger.warning("Transcript callback error: %s", exc)

            async def _on_error(dg_self, error, **kwargs):
                logger.warning("Deepgram error: %s", error)

            async def _on_open(dg_self, open, **kwargs):
                logger.info("Deepgram connection opened ✓")

            self._conn.on(LiveTranscriptionEvents.Open, _on_open)
            self._conn.on(LiveTranscriptionEvents.Transcript, _on_transcript)
            self._conn.on(LiveTranscriptionEvents.Error, _on_error)

            options = LiveOptions(
                model="nova-2",
                encoding="linear16",
                sample_rate=self._sample_rate,
                channels=1,
                interim_results=True,
                endpointing=500,
                smart_format=True,
            )
            await asyncio.wait_for(self._conn.start(options), timeout=8.0)
            return True
        except asyncio.TimeoutError:
            logger.warning("Deepgram connection timed out — falling back to browser STT")
            self._conn = None
            return False
        except Exception as exc:
            logger.error("Deepgram start failed: %s", exc)
            self._conn = None
            return False

    async def send(self, audio: bytes):
        if self._conn:
            try:
                await self._conn.send(audio)
            except Exception:
                pass

    async def close(self):
        if self._conn:
            conn = self._conn
            self._conn = None
            try:
                await asyncio.wait_for(conn.finish(), timeout=3.0)
            except Exception:
                pass
