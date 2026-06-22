import json
import re
from typing import Any, Optional
import anthropic

from app.config import settings
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools.web_search import web_search, TOOL_SPEC as WEB_SEARCH_SPEC
from app.agent.tools.fetch_url import fetch_url, TOOL_SPEC as FETCH_URL_SPEC
from app.agent.tools.rag_search import rag_search, TOOL_SPEC as RAG_SEARCH_SPEC
from app.agent.tools.calculator import calculator, TOOL_SPEC as CALC_SPEC
from app.observability.tracing import get_langfuse

_client: Optional[anthropic.AsyncAnthropic] = None
TOOLS = [WEB_SEARCH_SPEC, FETCH_URL_SPEC, RAG_SEARCH_SPEC, CALC_SPEC]


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def _execute_tool(name: str, inputs: dict) -> Any:
    lf = get_langfuse()
    with lf.start_as_current_observation(name=f"tool:{name}", as_type="tool", input=inputs):
        if name == "web_search":
            result = await web_search(**inputs)
        elif name == "fetch_url":
            result = await fetch_url(**inputs)
        elif name == "rag_search":
            result = await rag_search(**inputs)
        elif name == "calculator":
            result = calculator(**inputs)
        else:
            result = {"error": f"Unknown tool: {name}"}
        lf.update_current_span(output=result)
    return result


async def run_agent(
    user_message: str,
    conversation_history: list,
    memory_context: str = "",
    session_id: str = None,
) -> tuple[str, list]:
    """
    Full agentic loop: runs Claude with tool-calling until a final
    text response is produced. Returns (response_text, updated_history).
    Traces the full turn in Langfuse using nested spans/generations.
    """
    lf = get_langfuse()

    with lf.start_as_current_observation(
        name="voice_turn",
        as_type="agent",
        input={"user": user_message, "session_id": session_id},
    ):
        system = SYSTEM_PROMPT
        if memory_context:
            system += f"\n\n## Relevant past conversations\n{memory_context}"

        messages = list(conversation_history) + [{"role": "user", "content": user_message}]

        for _ in range(8):  # max tool-calling rounds
            with lf.start_as_current_observation(
                name="claude",
                as_type="generation",
                model=settings.claude_model,
                input=messages[-4:],   # last few turns for brevity in dashboard
            ):
                response = await _get_client().messages.create(
                    model=settings.claude_model,
                    max_tokens=1024,
                    system=system,
                    tools=TOOLS,
                    messages=messages,
                )
                lf.update_current_generation(
                    usage_details={
                        "input": response.usage.input_tokens,
                        "output": response.usage.output_tokens,
                    }
                )

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_parts = [b.text for b in response.content if b.type == "text"]

            if response.stop_reason == "end_turn" or not tool_uses:
                final_text = " ".join(text_parts).strip()
                messages.append({"role": "assistant", "content": response.content})
                lf.update_current_span(output={"response": final_text[:400]})
                return final_text, messages

            # Execute all tool calls in this round
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tu in tool_uses:
                result = await _execute_tool(tu.name, tu.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            messages.append({"role": "user", "content": tool_results})

        # Safety fallback: one final call without tools
        response = await _get_client().messages.create(
            model=settings.claude_model,
            max_tokens=512,
            system=system,
            messages=messages,
        )
        final = " ".join(b.text for b in response.content if hasattr(b, "text")).strip()
        messages.append({"role": "assistant", "content": response.content})
        return final, messages


# ── Streaming variant (used by the live voice session) ──────────────────────

# Emit a sentence only once its terminal punctuation is followed by whitespace,
# so mid-stream decimals ("2.5") and abbreviations aren't split prematurely.
_SENTENCE_RE = re.compile(r"[^.!?]*[.!?]+(?=\s)")


def _extract_sentences(buf: str):
    """Return (complete_sentences, remainder) from a growing text buffer."""
    sentences, last = [], 0
    for m in _SENTENCE_RE.finditer(buf):
        s = m.group().strip()
        if s:
            sentences.append(s)
        last = m.end()
    return sentences, buf[last:]


async def run_agent_streaming(
    user_message: str,
    conversation_history: list,
    memory_context: str = "",
    session_id: str = None,
    on_tool=None,       # async callback(tool_name)
    on_sentence=None,   # async callback(sentence_text) — fired as the answer streams
) -> tuple[str, list]:
    """
    Same agentic loop as run_agent, but streams the model output. Each completed
    sentence of the answer is handed to on_sentence as soon as it's generated, so
    the session can display it and synthesize speech while the rest is still being
    written — collapsing time-to-first-audio.
    """
    lf = get_langfuse()
    with lf.start_as_current_observation(
        name="voice_turn_stream", as_type="agent",
        input={"user": user_message, "session_id": session_id},
    ):
        system = SYSTEM_PROMPT
        if memory_context:
            system += f"\n\n## Relevant past conversations\n{memory_context}"

        messages = list(conversation_history) + [{"role": "user", "content": user_message}]

        for _ in range(8):
            buf, round_text = "", ""
            async with _get_client().messages.stream(
                model=settings.claude_model, max_tokens=1024,
                system=system, tools=TOOLS, messages=messages,
            ) as stream:
                async for event in stream:
                    if (event.type == "content_block_delta"
                            and getattr(event.delta, "type", None) == "text_delta"):
                        chunk = event.delta.text
                        round_text += chunk
                        buf += chunk
                        sentences, buf = _extract_sentences(buf)
                        for s in sentences:
                            if on_sentence:
                                await on_sentence(s)
                final = await stream.get_final_message()

            if buf.strip() and on_sentence:   # flush trailing partial sentence
                await on_sentence(buf.strip())

            tool_uses = [b for b in final.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": final.content})

            if final.stop_reason == "end_turn" or not tool_uses:
                lf.update_current_span(output={"response": round_text[:400]})
                return round_text.strip(), messages

            tool_results = []
            for tu in tool_uses:
                if on_tool:
                    try:
                        await on_tool(tu.name)
                    except Exception:
                        pass
                result = await _execute_tool(tu.name, tu.input)
                tool_results.append({
                    "type": "tool_result", "tool_use_id": tu.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            messages.append({"role": "user", "content": tool_results})

        # Safety fallback
        resp = await _get_client().messages.create(
            model=settings.claude_model, max_tokens=512, system=system, messages=messages,
        )
        answer = " ".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        if answer and on_sentence:
            await on_sentence(answer)
        messages.append({"role": "assistant", "content": resp.content})
        return answer, messages
