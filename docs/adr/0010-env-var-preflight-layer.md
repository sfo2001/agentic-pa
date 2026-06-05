# Each entry point pre-flights its expected env vars and prints a per-shell "how to set" hint on issue

The install / launch surface has five Python entry points (`install.py`, `setup_wizard.py`, `launch.py`, `launcher/run.py`, `frontend/app.py::build_default_app`) plus four shims (`setup.cmd`, `setup.sh`, `run.cmd`, `run.sh`). They each read a small set of environment variables — `INSTALL_ROOT`, `OPENCODE_PORT`, `WEB_PORT`, `LLM_WIKI_TOOLS`, `SETUP_MODE`, `NOTES_GIT_DIR`, etc. — but the prior shape had two recurring failures: silent defaults (the user is never told they forgot to set `INSTALL_ROOT`; it just falls back to `~/cos-notes` and the next downstream check explodes with a less-actionable error), and POSIX-flavored remediation copy in a codebase that ships `setup.cmd` for Windows users (`set PYTHON=...`, `~/cos-notes`, `set LLM_WIKI_TOOLS=/path`).

We add a single, quiet-by-default configuration preflight in `bootstrap_env.py` (`EnvSpec` + `preflight_env`) that every Python entry point calls at the top of `main()` / `build_default_app()`. The shims pick up the same coverage through their Python delegation. Output is plain text on stderr; the happy path emits nothing.

## Context

Two distinct problems with the same shape:

1. **Silent fallbacks hide the cause.** `INSTALL_ROOT` defaulted to `~/cos-notes` (or `%USERPROFILE%\cos-notes`); a user who forgot to set it saw "ERROR: {workspace} not found — run bootstrap first." with `workspace` pointing at a directory the user didn't choose. `OPENCODE_PORT=abc` raised an uncaught `ValueError`; the user got a Python traceback instead of "OPENCODE_PORT must be an integer." `SETUP_MODE=Target` (capital T) silently used venv mode, so a user on an AppLocker box who needed target mode got the wrong install.

2. **POSIX-only remediation copy.** The `run.sh` shim told the user "Install Python 3.10+ (or set PYTHON=…)" — fine for Linux/macOS, but the user on the managed Windows box that this whole project is *designed for* got the same string, with no mention of `winget`, the python.org installer, or `%LOCALAPPDATA%`. The `where py` probe is the only thing the .cmd shim can validate without invoking Python; everything else moves into the preflight where it can branch on `os.name`.

The prior preflight layer (the per-entry-point checks like `workspace.is_dir()`, `port_is_free()`, `_module_importable()`) is **runtime validation** — does the install actually work? — and stays. The new layer is **configuration validation** — did the user set the env vars they should have? — and lives one level up.

## Decision

1. **One helper, in `bootstrap_env.py`, stdlib-only.** `EnvSpec` is a frozen dataclass with `name`, `default`, `parser`, `required`, `hint`, `secret`. `preflight_env(specs)` walks the list, resolves each spec against `os.environ` + the spec's `default`, runs the optional `parser`, classifies the outcome as `ok` / `required-unset` / `optional-unset` / `parse-fail`. Quiet on success; on any issue, prints a unified table to stderr + per-shell "how to set" hints.

2. **Quiet by default — explicit user choice.** No output when every spec passes. The user only sees the preflight when something is wrong. Trade-off: less visibility into "what is the launcher actually using" by default; gain: zero noise on the happy path. (A future `INSTALL_VERBOSE=1` flag could re-enable the table-on-success path if needed; not in scope here.)

3. **Required → `sys.exit(2)`, optional → warn-and-continue.** The `required` flag is per-spec. The existing `RuntimeError` guard in `frontend/app.py::build_default_app` (for `NOTES_GIT_DIR`) is replaced by `EnvSpec(required=True)`; the test that pinned the `RuntimeError` contract is updated to expect `SystemExit(2)`. This is a strict UX improvement: the preflight's stderr message includes the per-shell hint, which the bare `RuntimeError` did not.

4. **Three shell hints on Windows, two on POSIX.** On `os.name == "nt"`: cmd + PowerShell + bash (covers WSL / git-bash users). On POSIX: bash + PowerShell (Core). No auto-detection of the user's actual interactive shell — detection is unreliable from inside Python, and printing all relevant options costs ~3 lines per unset var.

5. **Shims are thin interpreters, not preflights.** The shims' only responsibility is finding a base Python (`py -3` on Windows, `python3` on POSIX) and delegating. They get one new line each: a `where py` probe that fails loud on Windows when the Python launcher is missing (the corresponding `command -v` probe already exists in `run.sh` / `setup.sh`). Everything else moves into the Python entry point the shim delegates to.

6. **No pre-existing preflight is replaced.** `no_git_ancestor`, `port_is_free`, `_module_importable`, `_module_importable`-timeout-fails-closed, `require_tools` (the `shutil.which("opencode")` check) all stay. They answer "does the install work?" — the new layer answers "did the user set the env vars?" Different concerns, different layer, both necessary.

## Consequences

- The preflight helper itself is ~80 lines + tests, in a single file. No new dependencies.
- The wire-up at the 5 call sites is one `preflight_env([...])` call per site, each with a small list of `EnvSpec` entries. Total diff: ~50 lines of specs across the entry points.
- The shim changes are 6 lines per file. The .cmd files pick up Windows-aware error messages; the .sh files are unchanged.
- `OPENCODE_PORT` / `WEB_PORT` are now strictly typed at the preflight boundary; a malformed value is caught at start with a clear "must be an integer" message instead of a Python traceback. This is also a security win: a tampered env var that successfully passed `int()` validation is *not* a code-injection vector (the preflight passes the validated value through; the launcher's subprocess invocation uses the int directly as a CLI arg, which is shell-quoted by `subprocess.run`'s list form).
- The shim `where py` probe is structural-tested (the .cmd file is read and the probe text is asserted); the actual `errorlevel 1` behavior is only verifiable on a real Windows box. Acceptable trade-off — the structural test catches the regression where someone removes the probe while refactoring the shim, which is the failure mode the test was added for.
- Two pre-existing mypy issues (in `install.py::forced_target` and `launcher/run.py`'s `for p in reversed(procs):` loop narrowing) are NOT introduced by this change and are not addressed here. They predate the preflight series and can be cleaned up in a follow-up.
- `ruff.toml` gains `extend-exclude = ["*.cmd", "*.sh", "*.ps1"]` — ruff has no grammar for these and would report spurious parse errors. Their structure is covered by the new tests, not the linter.

## Could age badly

- The preflight's per-shell hint text is hand-written, not auto-generated from a `shlex`-style library. If we add support for fish / nushell / xonsh later, the `_shell_hints()` function needs a per-shell formatter, not just an extra line. A new contributor adding a shell would have to add a branch.
- The `secret=True` masking is presentation-only, not cryptographic. It's a stderr line that an end-user could trivially screenshot. Adequate for "don't leak an API key into a CI log", not adequate for any compliance regime that needs redaction. If a future feature requires compliance-grade redaction, a structured-logging library (e.g. `structlog`) would replace `print(..., file=sys.stderr)`.
- The `os.name == "nt"` branch in `_shell_hints` is binary. If a future contributor wants to detect WSL vs native Windows vs git-bash (where the right hint differs), this will need to become a richer classifier.
