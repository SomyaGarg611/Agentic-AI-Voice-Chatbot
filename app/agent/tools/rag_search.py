from typing import Optional


async def rag_search(query: str, top_k: int = 4) -> dict:
    try:
        from app.rag.store import get_store
        store = get_store()
        results = store.query(query, top_k=top_k)
        return {"query": query, "results": results}
    except Exception as e:
        return {"query": query, "error": str(e), "results": []}


TOOL_SPEC = {
    "name": "rag_search",
    "description": "Search the user's uploaded documents using semantic similarity. Use this when the user asks about content from documents they've shared, or for domain-specific knowledge not on the public internet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The semantic search query to find relevant document chunks.",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of document chunks to retrieve. Default 4.",
                "default": 4,
            },
        },
        "required": ["query"],
    },
}
