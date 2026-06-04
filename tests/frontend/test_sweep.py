"""Sweep module tests: watermark store + window slicing + capture/archive."""
import tempfile
from pathlib import Path

from frontend import sweep


def test_watermark_roundtrip():
    root = Path(tempfile.mkdtemp())
    assert sweep.read_watermark(root, "ses_1") is None
    sweep.write_watermark(root, "ses_1", "msg_42")
    assert sweep.read_watermark(root, "ses_1") == "msg_42"
    # per-session isolation
    assert sweep.read_watermark(root, "ses_2") is None
    sweep.write_watermark(root, "ses_2", "msg_7")
    assert sweep.read_watermark(root, "ses_1") == "msg_42"
    assert sweep.read_watermark(root, "ses_2") == "msg_7"


def test_watermark_survives_corrupt_file():
    root = Path(tempfile.mkdtemp())
    (root / ".sweep-state.json").write_text("not json", encoding="utf-8")
    assert sweep.read_watermark(root, "ses_1") is None  # fail-soft
    sweep.write_watermark(root, "ses_1", "msg_1")
    assert sweep.read_watermark(root, "ses_1") == "msg_1"


def test_watermark_with_git_dir_writes_outside_notes_root():
    """H-2: when ``git_dir=`` is supplied, the state file lives in the
    notes git-dir (NOT the notes_root sandbox).

    The security claim is that the agent's read_file/write_file tools
    cannot reach the state file because it's outside workspace/. This
    test pins that contract: the file appears under git_dir/ and nowhere
    under notes_root/.
    """
    root = Path(tempfile.mkdtemp())
    git_dir = Path(tempfile.mkdtemp())  # a separate dir, simulating notes.git/
    sweep.write_watermark(root, "ses_1", "msg_42", git_dir=git_dir)
    # The state file lives in the git-dir.
    state = git_dir / ".sweep-state.json"
    assert state.exists(), f"expected state at {state}"
    # And the watermark reads back from there.
    assert sweep.read_watermark(root, "ses_1", git_dir=git_dir) == "msg_42"
    # Critically, nothing under notes_root/ holds the state.
    assert not (root / ".sweep-state.json").exists()
    assert list(root.iterdir()) == [], (
        f"git_dir= mode leaked files into notes_root: {list(root.iterdir())}"
    )


def test_make_capture_stamp_includes_microseconds():
    """M-4: make_capture_stamp returns a 24-char stamp (YYYY-MM-DD-HHMMSS-ffffff)
    and two consecutive calls in a tight loop produce different strings.

    Pinning the contract against a regression to %H%M%S (the old format) that
    would cause same-second collision when the user mashes the Sweep button.
    """
    a = sweep.make_capture_stamp()
    b = sweep.make_capture_stamp()
    assert len(a) == 24, f"expected 24-char stamp, got {a!r}"
    assert a.count("-") == 4, f"expected 4 dashes (date, time, microsec), got {a!r}"
    # Same-second collision regression: two tight calls must differ.
    # Microsecond precision guarantees this in practice; if the impl drops
    # to %H%M%S, both stamps will collide and the test fails.
    assert a != b, f"two consecutive stamps collided: {a!r} == {b!r}"


def _msgs(*pairs):
    return [{"id": i, "role": r, "text": t} for (i, r, t) in pairs]


def test_slice_window_skips_up_to_and_excluding_watermark():
    msgs = _msgs(("m1", "user", "a"), ("m2", "assistant", "b"), ("m3", "user", "c"))
    window, last = sweep.slice_window(msgs, after_id="m1", budget=1000)
    assert [m["id"] for m in window] == ["m2", "m3"]
    assert last == "m3"


def test_slice_window_from_start_when_no_watermark():
    msgs = _msgs(("m1", "user", "a"), ("m2", "user", "b"))
    window, last = sweep.slice_window(msgs, after_id=None, budget=1000)
    assert [m["id"] for m in window] == ["m1", "m2"]
    assert last == "m2"


def test_slice_window_bounded_by_budget():
    msgs = _msgs(("m1", "user", "x" * 30), ("m2", "user", "y" * 30), ("m3", "user", "z" * 30))
    window, last = sweep.slice_window(msgs, after_id=None, budget=50)
    # First message (30 chars) fits; adding the second would exceed 50 → stop.
    assert [m["id"] for m in window] == ["m1"]
    assert last == "m1"


def test_slice_window_always_takes_at_least_one():
    msgs = _msgs(("m1", "user", "x" * 100))
    window, last = sweep.slice_window(msgs, after_id=None, budget=10)
    assert [m["id"] for m in window] == ["m1"]  # oversized lone message still taken
    assert last == "m1"


def test_slice_window_empty_when_caught_up():
    msgs = _msgs(("m1", "user", "a"))
    window, last = sweep.slice_window(msgs, after_id="m1", budget=1000)
    assert window == [] and last is None


def test_render_window_text_labels_roles():
    msgs = _msgs(("m1", "user", "revisit atlas"), ("m2", "assistant", "noted"))
    text = sweep.render_window_text(msgs)
    assert "**you:** revisit atlas" in text
    assert "**assistant:** noted" in text


def test_write_and_archive_capture():
    root = Path(tempfile.mkdtemp())
    path = sweep.write_capture(root, "raw braindump text", stamp="2026-06-04-1430")
    assert path == root / "inbox" / "2026-06-04-1430.md"
    assert path.read_text(encoding="utf-8") == "raw braindump text"
    sweep.archive_capture(root, path)
    assert not path.exists()
    assert (root / "archive" / "2026-06-04-1430.md").read_text(encoding="utf-8") == "raw braindump text"
