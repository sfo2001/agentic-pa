# Chief-of-Staff Notes Assistant

A locally-run, **fully-sandboxed** agentic assistant that acts as a chief of staff
for meeting notes and day/week organisation. It captures raw notes into a
topic-centric **Ground Truth** (topic → meeting → documents), triages the day/week
(Eisenhower quadrants + ticklers), and answers/drafts grounded in the local notes —
all on your machine, with no external systems.

The discipline lives where each part is strongest: a **deterministic agenda engine**
(code) guarantees nothing date-based ever slips, while the **LLM agent** (language)
parses notes, files them, and keeps the topic Ground Truth coherent.

> **Status:** Milestone 1 (local-only MVP) complete. Milestone 2 (external
> Confluence/Jira grounding, remote workspace, profiles) is the future north-star
> track — see `workspace-assistant-spec.md`.

## Architecture at a glance

```
browser ── HTTP/SSE ──► frontend (FastAPI)  ── HTTP ──►  opencode serve (127.0.0.1)
                          │  proxy + SSE relay              │  sandboxed agent
                          │  owns notes git (commit/undo)   └─ MCP ─► agenda server (read-only)
                          └─ uploads → workspace/documents/        (deterministic date logic)
```

| Package | Responsibility |
|---|---|
| `agenda/` | Deterministic, **read-only** agenda engine + MCP server (`notes_today/review/topic`). Parser → models → engine → FastMCP server. |
| `frontend/` | The sole OpenCode HTTP client: session proxy, SSE relay, browser API, document upload, notes git versioning, install bootstrap, config builder. |
| `launcher/` | One-command launcher: pre-flight, start OpenCode + frontend, health-gate, clean shutdown. |
| `notes-mvp/` | Dev helper: generates a local `opencode.json` against `sample-notes/`. |

The agent is confined to a notes-only `workspace/` leaf directory; config, secrets,
the system prompt, and the notes git metadata live in the **unreachable parent** —
see **ADR-0005** and `docs/decisions/D-opencode-sandbox.md`.

## Quickstart

Requires Python 3.12+, [`opencode`](https://opencode.ai) on `PATH`, an
OpenAI-compatible model endpoint (e.g. a local ollama), and
[`llm-wiki-tools`](https://github.com/sfo2001/llm-wiki-tools) checked out next to
this repo — it backs document ingest, structural linting, and BM25 search.

Clone both repos side by side so the sibling checkout resolves (or point
`LLM_WIKI_TOOLS` at it):

```bash
git clone https://github.com/sfo2001/llm-wiki-tools.git
git clone https://github.com/sfo2001/agentic-pa.git
cd agentic-pa
```

**Guided setup (recommended)** — creates the venv, installs everything, checks
your environment, then runs an interactive wizard that prompts for your endpoint
(offering a model pick-list), install location, and writes the install:

```bash
./setup.sh                       # Linux/macOS
# powershell -ExecutionPolicy Bypass -File setup.ps1   # Windows
```

**Manual** (equivalent to what the wizard does):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ../llm-wiki-tools -e ./agenda -e ./frontend -e ./presenter
pip install -r agenda/requirements-dev.txt -r frontend/requirements-dev.txt

# Bootstrap an install (config/secrets/git live OUTSIDE the agent sandbox):
python -c "from frontend.bootstrap import init_install; \
init_install('$HOME/cos-notes', model_endpoint='http://<host>:11434/v1', \
model_id='<model-id>', agenda_server='$PWD/.venv/bin/agenda-server')"

# Run it (Ctrl+C to stop) — use the venv's python so the installed deps are found:
INSTALL_ROOT=$HOME/cos-notes .venv/bin/python -m launcher.run
# → open http://127.0.0.1:8000/
```

See **[`docs/FIRST-RUN.md`](docs/FIRST-RUN.md)** for a fuller walkthrough.

## Documentation

- **Design (authoritative, Milestone 1):** `mvp-chief-of-staff-notes-design.md`
- **Glossary:** `CONTEXT.md`
- **Decisions:** `docs/adr/0001–0005`, `docs/decisions/D-opencode-{http,sandbox}.md`
- **Implementation plan:** `workspace-assistant-implementation-plan.md`

## Development

```bash
ruff check agenda frontend launcher notes-mvp tests   # lint
pytest tests/ -q                                       # unit tests (excludes the live smoke)
python tests/smoke/notes-mvp/run_smoke.py              # end-to-end (needs a live model)
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for conventions.

## License

[MIT](LICENSE) © 2026 Stefan Förster
