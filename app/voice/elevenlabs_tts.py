import asyncio
import logging
import re
from typing import AsyncIterator, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MAX_CHARS = 400   # safe per-request limit well under ElevenLabs 5 000-char max

# Reuse a single sync client across all sentences
_client = None

def _get_client():
    global _client
    if _client is None:
        from elevenlabs import ElevenLabs
        _client = ElevenLabs(api_key=settings.elevenlabs_api_key)
    return _client


def clean_for_tts(text: str) -> str:
    """Strip markdown so ElevenLabs speaks clean prose, not formatting symbols."""
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,2}([^_\n]+)_{1,2}", r"\1", text)
    text = re.sub(r"\[\d+\]\s*https?://\S+", "", text)   # [1] https://...
    text = re.sub(r"\[\d+\]", "", text)                   # bare [1]
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", " ", text)
    return text.strip()


def _split_sentences(text: str) -> List[str]:
    parts = _SENTENCE_RE.split(text.strip())
    sentences = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Safety: if a "sentence" is too long, chunk it at word boundaries
        while len(p) > _MAX_CHARS:
            cut = p.rfind(" ", 0, _MAX_CHARS)
            if cut == -1:
                cut = _MAX_CHARS
            sentences.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            sentences.append(p)
    return sentences


def _synthesize_sync(text: str) -> bytes:
    """Blocking ElevenLabs call — runs in a thread executor."""
    client = _get_client()
    buf = b""
    for chunk in client.text_to_speech.stream(
        voice_id=settings.elevenlabs_voice_id,
        text=text,
        model_id=settings.elevenlabs_model,
        output_format="pcm_16000",
    ):
        if isinstance(chunk, bytes):
            buf += chunk
    return buf


async def synthesize_sentence(text: str) -> bytes:
    if not settings.has_elevenlabs or not text.strip():
        return b""
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _synthesize_sync, text)
    except Exception as exc:
        logger.error("ElevenLabs TTS error for %r: %s", text[:40], exc)
        return b""


async def stream_tts(text: str) -> AsyncIterator[tuple[str, bytes]]:
    """
    Yields (sentence, pcm_bytes) one at a time, SEQUENTIALLY.
    Sequential avoids ElevenLabs concurrent-request rate limits on the free tier.
    The browser starts playing sentence 1 while sentence 2 is synthesising,
    so perceived latency stays low.
    """
    sentences = _split_sentences(clean_for_tts(text))
    if not sentences:
        return

    for sentence in sentences:
        audio = await synthesize_sentence(sentence)
        yield sentence, audio
