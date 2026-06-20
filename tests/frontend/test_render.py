from frontend.render import render_markdown


def test_renders_headings_lists_tables_code():
    html = render_markdown("# Title\n\n- a\n- b\n\n| h |\n|---|\n| c |\n\n    code\n")
    assert "<h1>" in html and "Title" in html
    assert "<li>" in html
    assert "<table>" in html and "<td>" in html        # tables must survive sanitization
    assert "<code>" in html or "<pre>" in html          # code blocks must survive


def test_sanitizes_script_and_handlers():
    html = render_markdown("ok\n\n<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>")
    assert "<script>" not in html
    assert "onerror" not in html


def test_strips_javascript_urls():
    html = render_markdown("[click](javascript:alert(1))")
    assert "javascript:" not in html


def test_sanitizes_style_and_vbscript():
    html = render_markdown('<p style="x:y">hi</p>\n\n[c](vbscript:msgbox(1))')
    assert "style=" not in html
    assert "vbscript:" not in html


# ── Bold-delimiter normalization (asymmetric ** spacing only) ────────────────


def test_bold_normalizes_asymmetric_open():
    """`** bold**` (space after opening) is the common LLM mistake → bold."""
    assert "<strong>bold</strong>" in render_markdown("** bold**")
    assert "<strong>bold</strong>" in render_markdown("**  bold**")  # multi-space


def test_bold_normalizes_asymmetric_close():
    """`**bold **` (space before closing) → bold."""
    assert "<strong>bold</strong>" in render_markdown("**bold **")


def test_bold_leaves_valid_bold_untouched():
    assert "<strong>tight</strong>" in render_markdown("a **tight** b")


def test_bold_leaves_symmetric_padded_alone():
    """`** x **` is ambiguous with the `**` operator — must NOT become bold."""
    assert "<strong>" not in render_markdown("** bold **")


def test_bold_lone_asymmetric_opener_without_closer_is_left_alone():
    """A `** word` with a leading space but no closing `**` on the same line
    must not be touched — the regex requires a complete matched pair."""
    assert "<strong>" not in render_markdown("** bold without any closing asterisks")


def test_bold_does_not_corrupt_power_operator():
    """`2 ** 8` and multi-operator lines must survive verbatim (regression for
    the two-global-subs bug that merged unrelated operators into a bold span)."""
    assert render_markdown("2 ** 8") == "<p>2 ** 8</p>"
    assert "<strong>" not in render_markdown("x = 2 ** 8 and y = 3 ** 2")
    assert "<strong>" not in render_markdown("a ** b ** c ** d")
