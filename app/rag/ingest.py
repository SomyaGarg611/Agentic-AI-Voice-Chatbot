import hashlib
import io
from typing import List, Tuple
from app.rag.store import get_store

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def _chunk_text(text: str, source: str) -> Tuple[List[str], List[dict], List[str]]:
    chunks, metas, ids = [], [], []
    start = 0
    idx = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end].strip()
        if chunk:
            chunk_id = hashlib.md5(f"{source}:{idx}".encode()).hexdigest()
            chunks.append(chunk)
            metas.append({"source": source, "chunk_index": idx})
            ids.append(chunk_id)
        start = end - CHUNK_OVERLAP
        idx += 1
    return chunks, metas, ids


def ingest_text(content: str, filename: str) -> int:
    chunks, metas, ids = _chunk_text(content, filename)
    get_store().add_documents(chunks, metas, ids)
    return len(chunks)


def ingest_bytes(data: bytes, filename: str) -> int:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        text = _extract_pdf(data)
    else:
        text = data.decode("utf-8", errors="replace")
    return ingest_text(text, filename)


def _extract_pdf(data: bytes) -> str:
    # PyMuPDF — best quality, handles modern PDFs (installed)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=data, filetype="pdf")
        pages = [page.get_text() for page in doc]
        doc.close()
        text = "\n".join(pages).strip()
        if text:
            return text
    except Exception:
        pass
    # Fallback: PyPDF2
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if text:
            return text
    except Exception:
        pass
    return data.decode("utf-8", errors="replace")
