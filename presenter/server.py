from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("present")

# Bare tool name — OpenCode namespaces it as present_<name> via the server key
# "present"; registering "present" yields the tool the agent calls as `present`.
TOOL_NAMES = ("present",)


@mcp.tool()
def present(path: str) -> dict:
    """Show a workspace file (markdown) in the user's Presentation pane.

    `path` is relative to the notes workspace (e.g. "meetings/2026-05-31/atlas.md").
    This is a UI signal: it does not read or modify the file. The frontend renders
    the file in the right-hand pane.
    """
    return {"ok": True, "presented": path}


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
