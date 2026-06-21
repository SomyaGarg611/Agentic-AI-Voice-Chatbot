import httpx
from typing import Optional


async def fetch_url(url: str, max_chars: int = 3000) -> dict:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)"
        }
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            raw_html = response.text

        try:
            import trafilatura
            text = trafilatura.extract(
                raw_html,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
            )
            if not text:
                text = raw_html[:max_chars]
        except Exception:
            text = raw_html[:max_chars]

        return {
            "url": url,
            "content": text[:max_chars] if text else "",
            "status": response.status_code,
        }
    except httpx.HTTPStatusError as e:
        return {"url": url, "error": f"HTTP {e.response.status_code}", "content": ""}
    except Exception as e:
        return {"url": url, "error": str(e), "content": ""}


TOOL_SPEC = {
    "name": "fetch_url",
    "description": "Fetch and extract the main text content from a URL. Use to read articles, papers, documentation, or any web page in full.",
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full URL to fetch.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return. Default 3000.",
                "default": 3000,
            },
        },
        "required": ["url"],
    },
}
