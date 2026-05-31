import pytest

from frontend.upload import lwt_convert, store_upload

CONVERT_EXTS = {".pdf", ".docx", ".pptx"}


def _fake_convert(data: bytes, suffix: str) -> str:
    return f"converted:{suffix}:{len(data)}"


def test_txt_stored_without_conversion(tmp_path):
    result = store_upload(tmp_path, "note.txt", b"hello", convert=_fake_convert)
    docs = tmp_path / "documents"
    assert (docs / "note.txt").read_bytes() == b"hello"
    assert not (docs / "note.txt.md").exists()
    assert result == {"stored": "documents/note.txt", "markdown": None}


def test_docx_stored_and_converted(tmp_path):
    result = store_upload(tmp_path, "deck.docx", b"\x50\x4b\x03\x04zip", convert=_fake_convert)
    docs = tmp_path / "documents"
    assert (docs / "deck.docx").exists()
    assert (docs / "deck.docx.md").read_text(encoding="utf-8") == "converted:.docx:7"
    assert result == {"stored": "documents/deck.docx", "markdown": "documents/deck.docx.md"}


def test_filename_is_sanitised(tmp_path):
    # path traversal / directory components stripped
    result = store_upload(tmp_path, "../../etc/passwd", b"x", convert=_fake_convert)
    docs = tmp_path / "documents"
    assert (docs / "passwd").exists()
    assert ".." not in result["stored"]


def test_empty_filename_rejected(tmp_path):
    with pytest.raises(ValueError):
        store_upload(tmp_path, "", b"x", convert=_fake_convert)


# ── BH-25: Pattern I — null byte in filename causes ValueError (not 400) ─────


def test_bh25_null_byte_filename_raises_valueerror_not_crash(tmp_path):
    """BH-25: store_upload() with a filename containing a null byte causes
    a ValueError from os.path operations (e.g. ``os.path.realpath()`` on
    ``Path("file\x00name.txt")``). This ValueError is NOT caught — it
    propagates as a 500 instead of a 400.

    The function should detect null bytes early and raise ValueError with a
    clear \"invalid filename\" message."""
    with pytest.raises(ValueError, match="invalid filename"):
        store_upload(tmp_path, "evil\x00file.txt", b"x", convert=_fake_convert)


# ── BH-34: Pattern I — store_upload silently overwrites existing files ────────


def test_bh34_upload_overwrites_existing_file(tmp_path):
    """BH-34: store_upload() overwrites an existing file of the same name.

    Overwrite is intentional — re-uploading a revised document replaces the
    previous version (single-user notes tree). Not a bug; by design."""
    store_upload(tmp_path, "n.txt", b"first", convert=_fake_convert)
    result = store_upload(tmp_path, "n.txt", b"second", convert=_fake_convert)
    assert result == {"stored": "documents/n.txt", "markdown": None}
    assert (tmp_path / "documents" / "n.txt").read_bytes() == b"second"


def test_dot_and_dotdot_rejected(tmp_path):
    with pytest.raises(ValueError):
        store_upload(tmp_path, ".", b"x", convert=_fake_convert)
    with pytest.raises(ValueError):
        store_upload(tmp_path, "..", b"x", convert=_fake_convert)


def test_lwt_convert_pdf_returns_markdown_with_traceability(tmp_path):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(40, 10, "Atlas migration kickoff")
    data = bytes(pdf.output())

    md = lwt_convert(data, ".pdf")

    assert "Atlas migration kickoff" in md
    assert md.startswith("---\n")          # traceability frontmatter present
    assert "ingest-backend:" in md


def test_lwt_convert_unsupported_suffix_raises():
    with pytest.raises(ValueError):
        lwt_convert(b"hello", ".xyz")
