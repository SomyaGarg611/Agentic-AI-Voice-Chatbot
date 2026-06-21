"""
Document ingestion pipeline.

  bytes ──▶ extract_blocks() ──▶ prose blocks ──▶ recursive token-aware splitter
                              └─▶ table blocks ──▶ row-grouped chunks (header repeated)
                                                        │
                                                        ▼
                                              ChromaDB upsert (deterministic ids)

Deterministic chunk ids (md5 of source + position) mean re-uploading the same
file overwrites its chunks instead of creating duplicates.
"""
import hashlib
from typing import List, Tuple, Dict, Any

from app.rag.store import get_store
from app.rag.extract import extract_blocks
from app.rag.splitter import split_text, count_tokens, CHUNK_TOKENS


def _meta_suffix(meta: Dict[str, Any]) -> str:
    """Human-readable location tag for a chunk, e.g. 'p3' or 'Sheet1'."""
    if "page" in meta:   return f"p{meta['page']}"
    if "slide" in meta:  return f"slide{meta['slide']}"
    if "sheet" in meta:  return f"sheet:{meta['sheet']}"
    if "table" in meta:  return f"table{meta['table']}"
    return ""


def _table_chunks(header: List[str], rows: List[List[str]], max_tokens: int) -> List[str]:
    """Group table rows into chunks, repeating the header in each for context."""
    header_line = " | ".join(str(h) for h in header)
    base_tokens = count_tokens(header_line)
    chunks: List[str] = []
    cur: List[str] = []
    cur_tokens = base_tokens

    for row in rows:
        line = " | ".join(str(c) for c in row)
        lt = count_tokens(line)
        if cur and cur_tokens + lt > max_tokens:
            chunks.append(header_line + "\n" + "\n".join(cur))
            cur, cur_tokens = [], base_tokens
        cur.append(line)
        cur_tokens += lt

    if cur:
        chunks.append(header_line + "\n" + "\n".join(cur))
    return chunks


def _build(data: bytes, filename: str) -> Tuple[List[str], List[dict], List[str]]:
    blocks = extract_blocks(data, filename)
    chunks: List[str] = []
    metas: List[dict] = []
    ids: List[str] = []

    for b_idx, block in enumerate(blocks):
        meta = block.get("meta", {})
        suffix = _meta_suffix(meta)

        if block["type"] == "table":
            texts = _table_chunks(block["header"], block["rows"], CHUNK_TOKENS)
        else:
            texts = split_text(block["text"])

        for c_idx, text in enumerate(texts):
            if not text.strip():
                continue
            cid = hashlib.md5(f"{filename}:{b_idx}:{c_idx}".encode()).hexdigest()
            chunk_meta = {"source": filename, "chunk_index": c_idx, "block": b_idx}
            chunk_meta.update(meta)
            if suffix:
                chunk_meta["location"] = suffix
            chunks.append(text)
            metas.append(chunk_meta)
            ids.append(cid)

    return chunks, metas, ids


def ingest_bytes(data: bytes, filename: str) -> int:
    chunks, metas, ids = _build(data, filename)
    get_store().add_documents(chunks, metas, ids)
    return len(chunks)


def ingest_text(content: str, filename: str) -> int:
    """Convenience for already-extracted plain text."""
    return ingest_bytes(content.encode("utf-8"), filename if "." in filename else filename + ".txt")
