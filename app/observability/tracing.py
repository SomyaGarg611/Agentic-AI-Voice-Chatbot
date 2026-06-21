"""
Langfuse 4.x tracing using start_as_current_observation context managers.
Falls back to a no-op implementation when keys are not configured.
"""
import contextlib
import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_langfuse: Optional[object] = None


class _NoopObs:
    """Context manager that does nothing — used when Langfuse is not configured."""
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    def __enter__(self): return self
    def __exit__(self, *_): pass


class _NoopLangfuse:
    def start_as_current_observation(self, **kwargs) -> _NoopObs: return _NoopObs()
    def update_current_span(self, **kwargs): pass
    def update_current_generation(self, **kwargs): pass
    def set_current_trace_io(self, **kwargs): pass
    def flush(self): pass


def get_langfuse():
    """Return the Langfuse client (real or no-op). Initialises on first call."""
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    if not settings.has_langfuse:
        _langfuse = _NoopLangfuse()
        return _langfuse
    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse 4.x tracing enabled → %s", settings.langfuse_host)
    except Exception as exc:
        logger.warning("Langfuse init failed (%s) — tracing disabled", exc)
        _langfuse = _NoopLangfuse()
    return _langfuse


def flush():
    """Flush pending events to Langfuse. Call on shutdown."""
    with contextlib.suppress(Exception):
        get_langfuse().flush()
