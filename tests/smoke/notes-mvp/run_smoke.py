"""End-to-end integration smoke test for the Chief-of-Staff Notes MVP.

NOT collected by pytest (no test_ functions, no Test classes, lives under
tests/smoke/ which is excluded from the default run). Run manually:

    MODEL_ENDPOINT=http://<your-ollama-host>:11434/v1 \
    MODEL_ID=<your-model-id> \
    python tests/smoke/notes-mvp/run_smoke.py

Both MODEL_ENDPOINT and MODEL_ID are REQUIRED (no defaults baked in — the repo
must not carry machine-specific hosts or model ids).

Prerequisites:
  - opencode is on PATH (``which opencode``)
  - The model endpoint is reachable and the model is loaded
  - agenda and presenter are importable under the venv interpreter (`python -m` spawn)
  - The frontend and launcher packages are importable (run from the repo root
    with the venv active, or PYTHONPATH set accordingly)

Exit code 0 only if all assertions PASS.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Resolve repo root so we can import the project packages when run from
# any working directory.  The script lives at tests/smoke/notes-mvp/run_smoke.py
# so the repo root is three levels up.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent            # tests/smoke/notes-mvp/
_REPO = _HERE.parent.parent.parent                 # <repo root>
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from frontend.bootstrap import init_install  # noqa: E402
from launcher.run import (  # noqa: E402
    _wait_health,
    isolated_env,
    no_git_ancestor,
    port_is_free,
)


# ---------------------------------------------------------------------------
# Configuration (from env with defaults matching the canonical stack)
# ---------------------------------------------------------------------------
def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"ERROR: {name} must be set (no machine-specific default is committed). "
                 f"Example: MODEL_ENDPOINT=http://<host>:11434/v1 MODEL_ID=<model>")
    return val


MODEL_ENDPOINT = _require_env("MODEL_ENDPOINT")
MODEL_ID = _require_env("MODEL_ID")

# Generous timeout for the turn — the model is a local 64k-context A3B.
TURN_TIMEOUT_S = int(os.environ.get("SMOKE_TURN_TIMEOUT", "180"))
# Shorter health-wait timeouts for the server processes themselves.
OC_HEALTH_TIMEOUT_S = int(os.environ.get("SMOKE_OC_HEALTH_TIMEOUT", "60"))
FRONTEND_HEALTH_TIMEOUT_S = int(os.environ.get("SMOKE_FRONTEND_HEALTH_TIMEOUT", "30"))

# Candidate ports — find free ones at runtime.
OC_PORT_START = 14096
FRONTEND_PORT_START = 18000

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_free_port(start: int) -> int:
    for p in range(start, start + 100):
        if port_is_free(p):
            return p
    raise RuntimeError(f"No free port found in range {start}–{start + 99}")


def _get_json(url: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _consume_sse(url: str, timeout: float) -> tuple[list[dict], bool, bool]:
    """Consume the SSE stream at *url* until a terminal event.

    Returns:
        (events, got_message_delta, got_done)

    Uses **httpx** streaming (not raw http.client): OpenCode/Starlette serve
    /event and /api/events as chunked text/event-stream, and a raw
    http.client reader truncates the chunked body early
    (RemoteProtocolError: incomplete chunked read), yielding 0 events. httpx
    reads the chunked stream correctly. See docs/decisions/D-opencode-http.md §8.
    """
    events: list[dict] = []
    got_message_delta = False
    got_done = False

    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as resp:
                if resp.status_code != 200:
                    print(f"  SSE GET returned HTTP {resp.status_code}", flush=True)
                    return events, got_message_delta, got_done
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload_str = line[len("data:"):].strip()
                    if not payload_str:
                        continue
                    try:
                        evt = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    events.append(evt)
                    etype = evt.get("type")
                    if etype == "message_delta":
                        got_message_delta = True
                    if etype in ("done", "error"):
                        got_done = (etype == "done")
                        return events, got_message_delta, got_done
    except httpx.RemoteProtocolError:
        # Server closed the stream (e.g. after the turn). Fine if we already
        # observed the terminal event above; otherwise reported by the caller.
        pass
    except httpx.HTTPError as exc:
        print(f"  SSE read error: {exc!r}", flush=True)

    if not got_done:
        print("  WARNING: SSE stream ended without a terminal 'done' event", flush=True)
    return events, got_message_delta, got_done


def _git_log_oneline(workspace: Path, git_dir: Path) -> list[str]:
    result = subprocess.run(
        ["git", f"--git-dir={git_dir}", f"--work-tree={workspace}", "log", "--oneline"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip().splitlines()


def _check(label: str, condition: bool, detail: str = "") -> bool:
    marker = PASS if condition else FAIL
    msg = f"  [{marker}] {label}"
    if detail:
        msg += f"  — {detail}"
    print(msg, flush=True)
    return condition


# ---------------------------------------------------------------------------
# Main smoke sequence
# ---------------------------------------------------------------------------

def run_smoke() -> int:
    """Run the full smoke sequence. Returns 0 on all-pass, 1 on any failure."""
    results: list[bool] = []

    # ------------------------------------------------------------------
    # 1. Locate required tools
    # ------------------------------------------------------------------
    print("\n=== Pre-flight ===", flush=True)
    if shutil.which("opencode") is None:
        print(f"  [{FAIL}] opencode not on PATH — abort", flush=True)
        return 1
    print(f"  opencode: {shutil.which('opencode')}", flush=True)

    # MCP servers run as `python -m <module>` using this interpreter (frontend.config).
    python_executable = sys.executable
    print(f"  interpreter: {python_executable}", flush=True)

    # ------------------------------------------------------------------
    # 2. Throwaway install root in /tmp
    # ------------------------------------------------------------------
    install_root = Path(tempfile.mkdtemp(prefix="smoke-notes-"))
    print(f"\n=== Bootstrap install at {install_root} ===", flush=True)

    try:
        info = init_install(
            install_root,
            model_endpoint=MODEL_ENDPOINT,
            model_id=MODEL_ID,
            python_executable=python_executable,
        )
    except RuntimeError as exc:
        print(f"  [{FAIL}] init_install failed: {exc}", flush=True)
        shutil.rmtree(install_root, ignore_errors=True)
        return 1

    workspace: Path = info["workspace"]
    git_dir: Path = info["git_dir"]

    # Guard: workspace must not be inside a git repo.
    if not no_git_ancestor(workspace):
        print(
            f"  [{FAIL}] workspace {workspace} is inside a git repo — "
            "install_root must be outside any git repo. Aborting.",
            flush=True,
        )
        shutil.rmtree(install_root, ignore_errors=True)
        return 1
    print(f"  workspace: {workspace}", flush=True)
    print(f"  git_dir:   {git_dir}", flush=True)
    print("  no_git_ancestor(workspace): OK", flush=True)

    # ------------------------------------------------------------------
    # 3. Drop a raw note into the inbox
    # ------------------------------------------------------------------
    note_path = workspace / "inbox" / "2026-05-31-smoke.md"
    note_path.write_text(
        "# Smoke test meeting\n\n"
        "## Topic: Platform reliability review\n\n"
        "## Actions\n"
        "- [ ] Follow up with the infrastructure team on alert thresholds\n"
        "- [ ] Schedule Q3 capacity planning session\n",
        encoding="utf-8",
    )
    print(f"  dropped note: {note_path}", flush=True)

    # ------------------------------------------------------------------
    # 4. Start opencode serve + frontend; health-gate both
    # ------------------------------------------------------------------
    oc_port = _find_free_port(OC_PORT_START)
    web_port = _find_free_port(FRONTEND_PORT_START)
    oc_url = f"http://127.0.0.1:{oc_port}"
    web_url = f"http://127.0.0.1:{web_port}"

    print(f"\n=== Starting services (oc={oc_port}, web={web_port}) ===", flush=True)

    oc_env = isolated_env(install_root)
    Path(oc_env["HOME"]).mkdir(parents=True, exist_ok=True)

    procs: list[subprocess.Popen] = []
    try:
        # opencode serve — cwd = workspace so its config walk-up finds opencode.json
        procs.append(subprocess.Popen(
            ["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(oc_port)],
            cwd=str(workspace),
            env=oc_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ))

        print(f"  waiting for opencode health ({OC_HEALTH_TIMEOUT_S}s)…", flush=True)
        if not _wait_health(f"{oc_url}/global/health", timeout=OC_HEALTH_TIMEOUT_S):
            print(f"  [{FAIL}] opencode did not become healthy in {OC_HEALTH_TIMEOUT_S}s", flush=True)
            return 1
        print("  opencode: healthy", flush=True)

        # uvicorn frontend — factory mode, env vars for the app
        frontend_env = {
            **os.environ,
            "OPENCODE_BASE_URL": oc_url,
            "NOTES_ROOT": str(workspace),
            "NOTES_GIT_DIR": str(git_dir),
        }
        procs.append(subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "--factory", "frontend.app:build_default_app",
                "--host", "127.0.0.1",
                "--port", str(web_port),
            ],
            env=frontend_env,
            cwd=str(_REPO),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ))

        print(f"  waiting for frontend health ({FRONTEND_HEALTH_TIMEOUT_S}s)…", flush=True)
        if not _wait_health(f"{web_url}/health", timeout=FRONTEND_HEALTH_TIMEOUT_S):
            print(f"  [{FAIL}] frontend did not become healthy in {FRONTEND_HEALTH_TIMEOUT_S}s", flush=True)
            return 1
        print("  frontend: healthy", flush=True)

        # ------------------------------------------------------------------
        # 5. Drive ONE turn. The real browser fires the POST and opens the SSE
        #    stream CONCURRENTLY: POST /api/message blocks server-side for the
        #    whole turn (OpenCode's message POST is synchronous), while
        #    GET /api/events relays deltas live off OpenCode's broadcast /event
        #    stream. We must therefore start the SSE consumer FIRST (so the relay
        #    is attached before the turn fires), then POST — otherwise the live
        #    events are gone by the time we connect.
        # ------------------------------------------------------------------
        print("\n=== Turn: 'Process the inbox.' ===", flush=True)
        message_text = "Process the inbox."

        sse_result: dict = {}

        def _run_sse():
            sse_result["data"] = _consume_sse(f"{web_url}/api/events", timeout=TURN_TIMEOUT_S)

        print(f"  opening SSE stream (timeout={TURN_TIMEOUT_S}s)…", flush=True)
        sse_thread = threading.Thread(target=_run_sse, daemon=True)
        sse_thread.start()
        # Give the relay a moment to connect to OpenCode's /event stream and
        # create/attach the session before the POST triggers the turn.
        time.sleep(1.5)

        try:
            # POST blocks until proxy.send() returns, which waits on the model —
            # a cold 64k-context turn is slow, so this matches the turn timeout.
            msg_resp = _post_json(f"{web_url}/api/message", {"text": message_text},
                                  timeout=TURN_TIMEOUT_S)
        except Exception as exc:
            print(f"  [{FAIL}] POST /api/message failed: {exc}", flush=True)
            return 1
        print(f"  POST /api/message → {msg_resp}", flush=True)

        # The turn is done server-side; the relay should have seen session.idle
        # and emitted 'done'. Wait for the consumer thread to finish.
        sse_thread.join(timeout=TURN_TIMEOUT_S)
        sse_events, got_delta, got_done = sse_result.get("data", ([], False, False))
        print(f"  received {len(sse_events)} SSE events", flush=True)

        tool_call_events = [e for e in sse_events if e.get("type") == "tool_call"]
        if tool_call_events:
            print(f"  tool_call events: {[e.get('name') for e in tool_call_events]}", flush=True)

        # ------------------------------------------------------------------
        # 6. Assertions
        # ------------------------------------------------------------------
        print("\n=== Assertions ===", flush=True)

        # (a) SSE stream had at least one message_delta and a terminal done
        results.append(_check(
            "SSE: at least one message_delta",
            got_delta,
            f"got_message_delta={got_delta}",
        ))
        results.append(_check(
            "SSE: terminal 'done' event",
            got_done,
            f"got_done={got_done}",
        ))

        # (b) workspace gained at least one new file under meetings/, topics/,
        #     or tasks.todo.txt was modified
        new_meetings = list((workspace / "meetings").glob("*")) if (workspace / "meetings").is_dir() else []
        new_topics = list((workspace / "topics").glob("*")) if (workspace / "topics").is_dir() else []
        tasks_file = workspace / "tasks.todo.txt"
        tasks_nonempty = tasks_file.exists() and tasks_file.stat().st_size > 0
        workspace_changed = bool(new_meetings or new_topics or tasks_nonempty)
        results.append(_check(
            "Workspace: file(s) created under meetings/ or topics/, or tasks.todo.txt modified",
            workspace_changed,
            f"meetings={len(new_meetings)}, topics={len(new_topics)}, tasks_nonempty={tasks_nonempty}",
        ))

        # (c) git log gained a turn commit; no .git at/above workspace.
        # The subject is now derived from the agent's end-of-turn CHANGELOG line
        # (falling back to the prompt), so we assert a fresh `notes:` commit landed
        # on top of the initial commit and surface the subject for inspection.
        log_lines = _git_log_oneline(workspace, git_dir)
        print(f"  git log: {log_lines[:5]}", flush=True)
        turn_commit = next(
            (ln for ln in log_lines if ln.split(" ", 1)[1:] and ln.split(" ", 1)[1].startswith("notes:")
             and "initialise" not in ln),
            None,
        )
        results.append(_check(
            "git log: a 'notes:' turn commit landed (subject = agent changelog or prompt)",
            turn_commit is not None,
            f"subject={turn_commit!r}",
        ))
        results.append(_check(
            "No .git at or above workspace (sandbox boundary intact)",
            no_git_ancestor(workspace),
        ))

        # (d) Presentation pane: /api/file renders a workspace artifact. The agent
        # MAY also have emitted present events; surface the count but don't require it.
        # NOTE: this block runs BEFORE /api/undo so the files still exist on disk.
        present_evts = [e for e in sse_events if e.get("type") == "present"]
        _meet = next(workspace.glob("meetings/**/*.md"), None)
        _rel = _meet.relative_to(workspace).as_posix() if _meet else "tasks.todo.txt"
        try:
            _fr = _get_json(f"{web_url}/api/file?path={_rel}", timeout=10.0)
            _ok = isinstance(_fr.get("html"), str) or isinstance(_fr.get("text"), str)
        except Exception as _exc:
            _ok = False
            _fr = {"error": repr(_exc)}
        results.append(_check(
            "GET /api/file renders an artifact",
            _ok,
            f"path={_rel} present_events={len(present_evts)}",
        ))

        # (e) POST /api/undo returns success and HEAD moves back
        log_before_undo = log_lines[:]
        try:
            undo_resp = _post_json(f"{web_url}/api/undo", {}, timeout=10.0)
        except Exception as exc:
            print(f"  [{FAIL}] POST /api/undo failed: {exc}", flush=True)
            results.append(False)
        else:
            print(f"  POST /api/undo → {undo_resp}", flush=True)
            undo_ok = undo_resp.get("ok") is True
            log_after_undo = _git_log_oneline(workspace, git_dir)
            # After revert_last, a NEW revert commit is added; HEAD moves forward one,
            # the original commit content is undone, so log length increases by 1
            head_moved = len(log_after_undo) != len(log_before_undo)
            results.append(_check(
                "POST /api/undo: ok=true",
                undo_ok,
                f"response={undo_resp}",
            ))
            results.append(_check(
                "POST /api/undo: git log changed (revert commit added)",
                head_moved,
                f"before={len(log_before_undo)} commits, after={len(log_after_undo)} commits",
            ))

    finally:
        # ------------------------------------------------------------------
        # Always tear down both processes and remove the temp dir
        # ------------------------------------------------------------------
        print("\n=== Teardown ===", flush=True)
        for p in reversed(procs):
            try:
                p.terminate()
            except OSError:
                pass
        for p in reversed(procs):
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    p.kill()
                except OSError:
                    pass
        shutil.rmtree(install_root, ignore_errors=True)
        print(f"  temp install removed: {install_root}", flush=True)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n=== Summary ===", flush=True)
    passed = sum(1 for r in results if r)
    total = len(results)
    all_pass = all(results)
    print(f"  {passed}/{total} checks passed", flush=True)
    if all_pass:
        print(f"  [{PASS}] ALL CHECKS PASSED", flush=True)
        return 0
    else:
        print(f"  [{FAIL}] {total - passed} CHECK(S) FAILED", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_smoke())
