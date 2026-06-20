# Split into trust-domain-separated repositories (not one repo per MCP)

**Date:** 2026-06-20 · **Status:** Proposed · **Scope:** Repository topology

**Related:** ADR-0005, ADR-0011, `docs/web-research-architecture.md §4`,
`docs/opencode-agentic-architecture.md §8`

---

## Context

The current `agentic-pa` repository is a monorepo containing:

- `agenda/` — the Ground Truth / notes MCP server (read-only, deterministic)
- `presenter/` — the presenter MCP server (write-gated, validates mutations)
- `frontend/` — FastAPI backend + browser UI + `opencode.json` generator
- `launcher/` — one-command launcher with preflight + process management
- `notes-mvp/` — dev helper (sample notes, local config generator)

The planned `web-researcher` capability (`web-research-architecture.md §4`) adds a
second OpenCode instance with a completely different trust profile: no credentials,
no write capability, untrusted-facing, processing hostile web content. It requires:

- Its own `opencode.json` restricting the tool surface to web tools only
- A hardened, SSRF-validating fetch/search MCP that processes hostile HTML
- A separate deployment (ideally its own host/container) with egress pointed at a
  forward proxy

The question this ADR answers: **how do we organise these repositories?**

---

## Decision

**Split by trust domain, not by MCP count.** Three repositories:

| Repository | Trust domain | Contents |
|---|---|---|
| `agentic-pa` | Privileged — holds secrets | Backend, frontend, launcher, `opencode.json` generator, agenda MCP, presenter MCP, research broker, airlock |
| `web-researcher` | Untrusted-facing — no secrets | Researcher `opencode.json` config, SSRF-validating fetch/search MCP server, localhost-bound request/response endpoint |
| `shared-contract` | Neutral | Versioned JSON envelope schema (§7 of `web-research-architecture.md`). Owned by the consumer (`agentic-pa`). |

**What stays in `agentic-pa`:**

- `agenda/` and `presenter/` — both are privileged MCPs that live alongside the
  Confluence PAT (future Milestone 2) and the notes git history. They belong in the
  same dependency closure as the privileged credentials they would hypothetically hold.
- `frontend/` and `launcher/` — these own the session, the git audit trail, and the
  `opencode.json` generator. Moving them out would leave `agentic-pa` with no app.
- The research **broker + airlock** — validation of data crossing the trust boundary
  must run in the consumer's domain. A compromised producer cannot be trusted to
  certify its own output.

**What goes into `web-researcher`:**

- The researcher `opencode.json` template (no credentials; web-only tool surface)
- The hardened SSRF-validating fetch MCP server (resolves IPs, validates hops,
  sanitizes HTML including invisible Unicode and bidi overrides)
- The hardened web search MCP (wraps a search API with the same output sanitization)
- A localhost-bound HTTP endpoint that the `agentic-pa` broker calls

**What goes into `shared-contract`:**

- The versioned JSON schema for the research findings envelope (draft in
  `web-research-architecture.md §7`)
- Schema version history and a changelog
- A minimal validator utility importable by both sides

**Dependency direction:**

```
agentic-pa (consumer)
  ├── depends on: shared-contract (for schema + validator)
  └── calls:      web-researcher (HTTP, localhost-bound)

web-researcher (producer)
  └── conforms to: shared-contract (emits envelopes matching the schema)

shared-contract (neutral)
  └── owned by: agentic-pa (consumer sets the contract)
```

`web-researcher` never imports from `agentic-pa`. The dependency arrow flows only
one way: toward the shared contract, and the consumer owns the contract.

---

## Considered Alternatives

### A. Keep everything in `agentic-pa` (mono-repo)

**Rejected.** A transitive vulnerability in the HTML parser used by the SSRF fetch
MCP (which processes hostile web content) would live in the same dependency closure
as the Confluence PAT and the notes corpus. The repo boundary enforces that the two
dependency closures never intersect, making it impossible for a fetch-MCP vuln to
transitively reach the privileged credentials — not because of a policy rule, but
structurally.

### B. One repo per MCP server (four repos: agenda, presenter, fetch, search)

**Rejected.** `agenda/` and `presenter/` are both privileged MCPs. They belong in
the same dependency closure as `frontend/` and `launcher/` — they share validation
constants (`frontend/proposal.py` is the shared source of truth imported by both),
package install infrastructure, and the notes git logic. Splitting them into their
own repos would require packaging and cross-repo dependency management for code that
has no separate trust profile from the rest of `agentic-pa`. The split criterion is
trust domain, not process count.

### C. Path-based trust within the mono-repo

**Rejected.** Git repositories enforce no security properties at runtime. Three
packages in the same repo still share the same process namespace, the same `pip`
install, and the same dependency resolution. Putting `web-researcher/` in a subdir
of `agentic-pa` does not prevent a vulnerable `web-researcher` package from being
imported by `agentic-pa` code (e.g., via an accidental `from web_researcher import
...` or a shared transitive dep). Physical repo separation is the only way to make
the dependency closures actually independent.

---

## Migration Sequence

The migration is **additive** — no existing `agentic-pa` code needs to move.
Web-researcher and shared-contract are new projects built alongside `agentic-pa`.

1. **Create `shared-contract`** — extract the envelope schema from
   `web-research-architecture.md §7`, tag `v0.1.0`, publish (or install locally
   with `pip install -e`).

2. **Create `web-researcher`** — new repo with:
   - Researcher `opencode.json` template
   - SSRF-validating fetch MCP (implement §6.1 requirements)
   - Web search MCP with output sanitization
   - Localhost-bound HTTP endpoint (request/response, authed with a shared secret)
   - Import `shared-contract` for the schema and emit compliant envelopes

3. **Add broker + airlock to `agentic-pa`** — new module in `frontend/` or as
   a standalone service module:
   - Exposes `research(query, urls?)` tool to the primary agent
   - Forwards to `web-researcher` endpoint
   - Validates response against `shared-contract` schema
   - Runs deterministic sanitization pass (no model; strip invisible Unicode,
     bidi overrides, etc.)
   - Returns sanitized findings as the tool result
   - Import `shared-contract` for the schema

4. **Wire to the primary agent** — add `research_*` MCP tool surface to the
   primary's `opencode.json` permission block; update the system prompt.

5. **Deploy `web-researcher` separately** — on its own host/container with egress
   pointed at a forward proxy holding an allowlist. This is when the physical
   network isolation actually enforces what the repo separation sets up. Until then,
   SSRF hardening in the MCP code is the sole defense.

---

## Versioning and Packaging

- Each repository publishes its own Python package (`agenda_service`, `presenter_service`,
  `notes_frontend` from `agentic-pa`; a new `web_researcher` package; a new
  `shared_contract` package).
- `agentic-pa` pins `shared-contract` to a specific version in its `requirements`
  file (not a floating `>=`). Schema changes are **breaking** for the airlock
  validator — pin tightly.
- `web-researcher` also pins `shared-contract` to the same version for the same
  reason; a schema version mismatch between producer and consumer is a silent bug.
- The `shared-contract` schema version is included in every envelope (`"schema_version"`
  field) so the airlock can reject envelopes from a stale producer.

---

## Consequences

- **Positive:** The SSRF/HTML-parsing attack surface is structurally separated from
  the privileged credential store. A compromised `web-researcher` process cannot
  transitively reach `agentic-pa`'s secrets.
- **Positive:** `web-researcher` can use a different (cheaper, EU-cloud) model
  without affecting the primary's data-class constraints.
- **Positive:** `web-researcher` can be deployed, restarted, and updated
  independently of the primary agent.
- **Negative:** Two `opencode serve` lifecycles to manage (the launcher in
  `agentic-pa` must optionally start the researcher, or it runs standalone).
- **Negative:** Schema evolution in `shared-contract` requires coordinated version
  bumps in both `agentic-pa` and `web-researcher`.
- **Negative:** The `shared-contract` ownership rule (consumer owns the schema) is
  a social/process constraint, not a technical one — it can be violated if the
  `web-researcher` team adds fields the consumer never validated.

---

## Could Age Badly

- **Interface drift** — if `web-researcher` becomes complex enough to have its own
  opinionated data model, pressure will build to put the schema in `web-researcher`
  instead of `shared-contract`. This inverts the ownership rule and makes the
  producer the validator — the exact failure mode the broker+airlock design prevents.
  Resist it; the schema belongs to the consumer.
- **Shared-contract churn** — early iteration on the envelope schema will require
  coordinated bumps. If iteration speed is important, temporarily accept that both
  repos are pinned to `shared-contract` HEAD rather than a tagged release.
- **Network-namespace backstop not yet in place** — until `web-researcher` runs on
  its own host/container with a proxy allowlist, the SSRF hardening in the fetch
  MCP code is the *only* defense (there is no network backstop). Document this
  explicitly in `web-researcher`'s README; do not allow the gap to be treated as
  acceptable long-term.

---

## References

- `docs/web-research-architecture.md §4` — origin of the 3-repo topology
- `docs/web-research-architecture.md §3` — the trust model that motivates the split
- `docs/adr/0005-sandbox-is-a-notes-only-leaf.md` — why the agent's sandbox must be isolated from the install-root
- `docs/adr/0011-restrict-write-mode-frontend-sole-writer.md` — the broader pattern of structural (not instructed) capability isolation
- `docs/opencode-agentic-architecture.md §7-§8` — the multi-instance pattern and topology table
