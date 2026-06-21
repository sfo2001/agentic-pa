from __future__ import annotations
import os
import httpx
from mcp.server.fastmcp import FastMCP
from ._airlock import AirlockError, validate_envelope

mcp = FastMCP("research")

# Tool name is "query" (bare) + server name "research" → OpenCode exposes as "research_query".
# Permission block uses "research_*": "allow" to cover all tools from this server.


@mcp.tool()
def query(query: str, urls: str | None = None) -> str:
    """Search the web and return sanitized Research findings.

    The primary agent has no web access; this tool delegates to the isolated
    Web Researcher service and validates the response through a deterministic
    airlock before returning anything to the agent.

    Args:
        query: What to research (max 500 chars).
        urls: Optional comma-separated list of specific URLs to fetch.
    """
    payload: dict = {"query": query[:500]}
    if urls:
        parsed_urls = [u for u in (s.strip() for s in urls.split(",")) if u][:5]
        if parsed_urls:
            payload["urls"] = parsed_urls

    researcher_url = os.environ.get("RESEARCHER_URL", "http://127.0.0.1:5100")
    secret = os.environ.get("RESEARCHER_SECRET", "")
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}

    try:
        resp = httpx.post(
            f"{researcher_url}/research",
            json=payload,
            headers=headers,
            timeout=60.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return f"ERROR: Web Researcher returned {exc.response.status_code}"
    except httpx.RequestError as exc:
        return f"ERROR: Web Researcher unavailable — {exc}"

    try:
        envelope = validate_envelope(resp.text)
    except AirlockError as exc:
        return f"ERROR: airlock rejected response — {exc}"

    lines = [f"Research: {envelope['query']}\n"]
    for i, f in enumerate(envelope["findings"], 1):
        lines.append(f"{i}. {f['claim']}")
        lines.append(f"   Source: {f['source_url']}")
    if not envelope["findings"]:
        lines.append("No findings returned.")
    return "\n".join(lines)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
