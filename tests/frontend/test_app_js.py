"""Pytest wrapper for tests/frontend/test_app_js.test.mjs.

Spawns `node` against the JS test harness so the test gets picked up by
`pytest tests/` (the project's standard gate). The Node test exercises
`checkPendingProposal` end-to-end with a minimal DOM + fetch mock — the
gap Agent 2 flagged as HIGH-2 in the propose-native-params audit.

The test is intentionally Node-only (no jsdom, no test framework); the
wrapper just reports the harness's exit code. If node is missing the
test is xfailed (we don't fail the gate — the change is a
`actions/setup-node` step in CI, not a hard runtime dep for the Python
project).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
JS_TEST = HERE / "test_app_js.test.mjs"


def _has_node() -> bool:
    return shutil.which("node") is not None


@pytest.mark.skipif(not _has_node(), reason="node not installed")
def test_app_js_check_pending_proposal() -> None:
    """Run the Node test harness; assert exit 0 and that all 5 cases passed."""
    assert JS_TEST.exists(), f"missing JS test harness: {JS_TEST}"
    proc = subprocess.run(
        ["node", str(JS_TEST)],
        capture_output=True,
        text=True,
        check=False,
        cwd=HERE.parent.parent,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    # The harness prints a `N passed, M failed` summary on the last line.
    summary = out.strip().splitlines()[-1] if out.strip() else ""
    assert proc.returncode == 0, (
        f"node test_app_js.test.mjs failed (rc={proc.returncode}):\n{out}"
    )
    assert summary.startswith("5 passed"), (
        f"expected all 5 JS cases to pass; got: {summary!r}\n--- full output ---\n{out}"
    )
