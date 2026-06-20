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


# Asymmetric ``**`` pairs only: a space on exactly ONE inner side, tight on the
# other. This is the common LLM mistake (``** bold**`` / ``**bold **``) and is
# *unambiguous* — the tight side proves intent to bold. Symmetric ``** x **`` is
# deliberately left alone: it is indistinguishable from the ``**`` operator
# (``2 ** 8``, ``a ** b``), so normalising it would corrupt prose/math. The
# ``[^*\n]`` inner class can't cross another ``**`` or a newline, so unrelated
# operators on the same line never get paired into one span.
_BOLD_OPEN_RE = re.compile(r"\*\* +(\S(?:[^*\n]*?\S)?)\*\*")   # ``** bold**``
_BOLD_CLOSE_RE = re.compile(r"\*\*(\S(?:[^*\n]*?\S)?) +\*\*")  # ``**bold **``


def _normalize_bold_delimiters(text: str) -> str:
    """Tighten *asymmetric* ``**`` pairs so ``** bold**`` renders as bold.

    LLMs commonly emit ``** bold**`` (space after the opening ``**``) or
    ``**bold **`` (space before the closing ``**``), which CommonMark rejects as
    emphasis. We strip the stray inner space only when the other side is already
    tight. Fully space-padded ``** x **`` and the ``**`` operator (``2 ** 8``)
    are intentionally untouched — see the comment on the patterns above.
    """
    text = _BOLD_OPEN_RE.sub(r"**\1**", text)
    text = _BOLD_CLOSE_RE.sub(r"**\1**", text)
    return text
