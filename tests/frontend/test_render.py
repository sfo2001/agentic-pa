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
