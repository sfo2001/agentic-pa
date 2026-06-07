"""Render workspace markdown to sanitized HTML for the Presentation pane.

Sanitization is the security boundary: model-written / markitdown-converted content
is untrusted, so the rendered HTML is passed through nh3 (strips <script>, event
handlers, javascript: URLs, and disallowed tags) before it reaches the browser.
"""
from __future__ import annotations

import re

import markdown as _markdown
import nh3

MAX_DIARY_RENDER_BYTES = 256 * 1024  # F4: a single day's accreted diary is KBs;
# anything past 256 KiB is rendered as an empty-state hint, not inlined.

# Tags that safe workspace markdown legitimately needs. We enumerate them
# explicitly so nh3's whitelist stripping cannot accidentally drop structural
# elements (tables, code blocks) while still rejecting <script>, <iframe>,
# event handlers, and javascript: URLs.
_ALLOWED_TAGS: frozenset[str] = frozenset({
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "ul", "ol", "li",
    "blockquote",
    "pre", "code",
    "em", "strong", "del", "s",
    "a",
    "img",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "div", "span",
})


def render_markdown(text: str) -> str:
    """Markdown string -> sanitized HTML string (safe to inject into the pane)."""
    text = _normalize_bold_delimiters(text)
    raw_html = _markdown.markdown(text, extensions=["extra", "sane_lists", "tables"])
    return nh3.clean(raw_html, tags=_ALLOWED_TAGS)


def _normalize_bold_delimiters(text: str) -> str:
    """Strip whitespace inside ``**`` pairs so ``** bold**`` renders as bold.

    LLMs commonly emit ``** bold**`` (space after the opening ``**``), which is
    invalid markdown and renders as literal asterisks.  This normalises both the
    opening and closing sides without changing valid ``**bold**``.
    """
    text = re.sub(r"\*\* +(\S)", r"**\1", text)
    text = re.sub(r"(\S) +\*\*", r"\1**", text)
    return text
