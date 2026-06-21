from typing import Optional
from app.config import settings


async def web_search(query: str, max_results: int = 5) -> dict:
    if not settings.has_tavily:
        return {"error": "Web search is not configured (no TAVILY_API_KEY).", "results": []}

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=True,
        )
        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:800],
                "score": r.get("score", 0),
            })
        return {
            "answer": response.get("answer", ""),
            "results": results,
        }
    except Exception as e:
        return {"error": str(e), "results": []}


TOOL_SPEC = {
    "name": "web_search",
    "description": "Search the internet for current information. Use for recent news, facts, data, prices, or anything that requires up-to-date knowledge.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Be specific and include key terms.",
            },
            "max_results": {
                "type": "integer",
                "description": "Number of results to return (1-10). Default 5.",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}
