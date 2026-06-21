"""
Token-aware recursive text splitter.

Splits text on a hierarchy of natural separators (paragraph → line → sentence
→ clause → word), keeping each chunk within a token budget tuned to the
embedding model, then re-merges adjacent pieces with overlap so context that
straddles a boundary is preserved in both neighbours.

Why token-aware: ChromaDB's default embedder (all-MiniLM-L6-v2) truncates input
at ~256 word-piece tokens. Chunks larger than that lose their tail at embed time,
silently degrading retrieval. We size chunks comfortably under that ceiling.
"""
from typing import List

# Sentence-transformer all-MiniLM-L6-v2 truncates at 256 wordpiece tokens.
# We measure with tiktoken (BPE) as a fast proxy and stay well under the ceiling.
CHUNK_TOKENS = 220
OVERLAP_TOKENS = 40

# Highest → lowest priority. Empty string = hard token split (last resort).
SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))

    def _hard_split(text: str, max_tokens: int) -> List[str]:
        toks = _enc.encode(text)
        out = []
        for i in range(0, len(toks), max_tokens):
            piece = _enc.decode(toks[i:i + max_tokens]).strip()
            if piece:
                out.append(piece)
        return out

except Exception:  # pragma: no cover - tiktoken always present in this project
    # Fallback: ~4 chars per token heuristic
    def count_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def _hard_split(text: str, max_tokens: int) -> List[str]:
        size = max_tokens * 4
        return [text[i:i + size].strip() for i in range(0, len(text), size) if text[i:i + size].strip()]


def _recursive_split(text: str, max_tokens: int, separators: List[str]) -> List[str]:
    """Break text into atomic pieces, each <= max_tokens, on the best boundary."""
    text = text.strip()
    if not text:
        return []
    if count_tokens(text) <= max_tokens:
        return [text]

    for i, sep in enumerate(separators):
        if sep == "":
            return _hard_split(text, max_tokens)
        if sep in text:
            parts = [p for p in text.split(sep) if p.strip()]
            if len(parts) <= 1:
                continue  # separator didn't actually divide anything useful
            out: List[str] = []
            for part in parts:
                if count_tokens(part) <= max_tokens:
                    out.append(part.strip())
                else:
                    out.extend(_recursive_split(part, max_tokens, separators[i + 1:]))
            return [o for o in out if o]

    return _hard_split(text, max_tokens)


def _merge_with_overlap(pieces: List[str], max_tokens: int, overlap_tokens: int) -> List[str]:
    """Greedily combine atomic pieces into chunks, carrying overlap between them."""
    chunks: List[str] = []
    cur: List[str] = []
    cur_tok = 0

    for piece in pieces:
        pt = count_tokens(piece)
        if cur and cur_tok + pt > max_tokens:
            chunks.append(" ".join(cur).strip())
            # Carry the trailing pieces (~overlap_tokens) into the next chunk
            overlap: List[str] = []
            otok = 0
            for q in reversed(cur):
                qt = count_tokens(q)
                if otok + qt > overlap_tokens:
                    break
                overlap.insert(0, q)
                otok += qt
            cur = overlap
            cur_tok = otok
        cur.append(piece)
        cur_tok += pt

    if cur:
        chunks.append(" ".join(cur).strip())
    return [c for c in chunks if c]


def split_text(text: str, max_tokens: int = CHUNK_TOKENS, overlap_tokens: int = OVERLAP_TOKENS) -> List[str]:
    """Public API: recursive, token-aware, overlapping chunks."""
    pieces = _recursive_split(text, max_tokens, SEPARATORS)
    return _merge_with_overlap(pieces, max_tokens, overlap_tokens)
