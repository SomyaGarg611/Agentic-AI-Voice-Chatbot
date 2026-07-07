import ipaddress
import socket
from urllib.parse import urlparse, urljoin

import httpx


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Block non-http(s) schemes and hosts that resolve to internal addresses (SSRF)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False, "only http/https URLs are allowed"
    host = p.hostname
    if not host:
        return False, "URL has no host"
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False, "could not resolve host"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False, "blocked: URL resolves to an internal address"
    return True, ""


async def fetch_url(url: str, max_chars: int = 3000) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)"}
    try:
        # Follow redirects manually so every hop is re-validated (a public URL
        # could 302 to an internal one to bypass the check).
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for _ in range(4):
                ok, reason = _is_safe_url(url)
                if not ok:
                    return {"url": url, "error": reason, "content": ""}
                response = await client.get(url, headers=headers)
                if response.status_code in (301, 302, 303, 307, 308) and "location" in response.headers:
                    url = urljoin(url, response.headers["location"])
                    continue
                break
            else:
                return {"url": url, "error": "too many redirects", "content": ""}

        response.raise_for_status()
        raw_html = response.text

        try:
            import trafilatura
            text = trafilatura.extract(
                raw_html, include_comments=False, include_tables=True, no_fallback=False,
            ) or raw_html[:max_chars]
        except Exception:
            text = raw_html[:max_chars]

        return {"url": url, "content": text[:max_chars] if text else "", "status": response.status_code}
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
            "url": {"type": "string", "description": "The full URL to fetch."},
            "max_chars": {"type": "integer", "description": "Maximum characters to return. Default 3000.", "default": 3000},
        },
        "required": ["url"],
    },
}
