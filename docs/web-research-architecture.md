# Web Research Capability — Architecture & Handoff

**Status:** Design agreed, pre-implementation
**Scope:** Adds untrusted web search/fetch to the agentic-pa system via an isolated specialist researcher
**Relationship to existing work:** Extends the agentic-pa system spec (dual-role Grounding/Workspace model). This capability is a new, separately-deployed component, not a tool added to the existing primary agent.

---

## 1. Goal

Give agentic-pa the ability to use web search and fetch **without** reintroducing general internet egress into the Confluence-capable agent. The existing spec's strongest property is that the primary agent has *no general internet access* (built-in `webfetch`/`websearch` denied; only outbound paths are the Confluence MCP backend and the model endpoint). Adding web access naively would delete that invariant. This design preserves it by keeping all web capability in a separate, capability-isolated process.

## 2. Chosen approach — the "strong route"

A **dedicated, sandboxed OpenCode-based web researcher**, deployed as its own project/service, exposing only web tools. The Confluence-capable primary never touches the web directly; it delegates via a broker and receives **structured, sanitized findings** back.

Rationale: this converts a hard problem (capability containment of an egress-capable agent) into a smaller one (content trust at a single validated boundary). An injection landing in the researcher cannot exfiltrate (no secrets, allowlisted egress) and cannot write (no Confluence, no workspace) — it can only attempt to push a *string* across the boundary, where deterministic validation and a human diff gate catch it.

## 3. Trust model — read this first

Two framing corrections that drive the whole design:

- **This is capability isolation, NOT an air gap.** There is a deliberate, live data path (query out, findings back). The security lives in the *validation of what crosses*, not in any gap. Treating it as an air gap invites under-investing in the airlock, which is the load-bearing component.
- **Repos are not the trust boundary; the runtime is.** Three git projects organize code but enforce no security properties by themselves — three processes still share a host, network namespace, and filesystem unless deployed apart. The real isolation comes from running the researcher on its **own host/VM/container with an independent egress path**. The repo split exists to *enable* that deployment cleanly.

Directional isolation that IS real and intended: researcher → (no path to) Confluence, secrets, or workspace write.

## 4. Project topology

| Project | Trust domain | Contents |
|---|---|---|
| `agentic-pa` | Privileged + validation authority | Backend, frontend, launcher, primary OpenCode config, Confluence MCP server, **research-broker + airlock** |
| `web-researcher` | Untrusted-facing | Researcher OpenCode config (web-only tool surface), hardened SSRF-validating fetch/search MCP server, localhost-bound request/response endpoint. Emits **raw candidate** envelopes. |
| `shared-contract` (small) | Neutral | Versioned envelope schema, owned by the **consumer** (agentic-pa) since it is the party that must trust the data. |

**Split by trust level, not by "it's an MCP server."** Do not lump all MCP servers into one repo: the web fetch server (eats hostile input) and the Confluence server (holds the PAT) belong in different dependency closures. A transitive vuln in the HTML parser must not live in the same tree as the Confluence credential.

## 5. Component responsibilities

**Researcher instance (`web-researcher`)**
- OpenCode `serve`, localhost-bound, owned/launched by the agentic-pa backend (or deployed standalone on its own host).
- Tool surface: hardened web search + fetch **only**. No Confluence MCP, no workspace MCP, no `bash`, no `task`/subagents, file tools denied.
- Built-in `webfetch`/`websearch` **denied** here too — all egress goes through the custom SSRF-validating server, never OpenCode's built-in fetch (which we don't control).
- May run a different (cheaper, EU-cloud) model: it only ever sees public web content, so it is free of the data-class constraint that pins the primary to a local/approved endpoint.

**Research-broker + airlock (lives in `agentic-pa`)**
- The *only* bridge between primary and researcher.
- Exposes one tool to the primary: `research(query, urls?)`.
- Forwards to the researcher, receives the raw candidate envelope, **validates and neutralizes it**, returns sanitized findings as the tool result.
- **Critical placement rule:** the airlock runs in agentic-pa's trust domain, never the researcher's. A compromised producer cannot be trusted to certify its own output. Validate on the boundary you control, as the consumer.

**Primary instance (`agentic-pa`)**
- Unchanged Confluence grounding + workspace, plus the `research(...)` tool.
- No web tools of any kind. Its process tree never contains a fetch primitive.

## 6. Security controls

### 6.1 Researcher egress (SSRF) — simpler and stricter than the single-agent route
Because the researcher has no legitimate internal needs, its policy is total: **deny all RFC-1918 ranges and the entire LAN, unconditionally** — including the on-prem Confluence Data Center host. No carve-outs. Fetch server must:
- Reject non-`http(s)` schemes (`file:`, `data:`, `gopher:`, `ftp:`).
- Resolve the hostname and reject if the **resolved IP** is in `127/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16` (incl. cloud metadata), `::1`, `fc00::/7`, `fe80::/10`, `0.0.0.0/8`. Validate the resolved address, not the hostname string.
- Follow redirects **manually**, re-validating every hop's `Location` (an allowed host can 302 into localhost / LAN).
- Connect to the validated IP with explicit `Host` (mitigate DNS rebinding). Cap redirects, timeout, response size.

> Why LAN denial matters specifically here: an SSRF-vulnerable fetch tool could otherwise reach the internal Confluence REST API directly, bypassing the subtree-restriction wrapper that is the entire enforcement boundary of agentic-pa.

### 6.2 No network-namespace backstop by default
With stdio MCP servers sharing the host netns, the SSRF validation **in the fetch server's own code is the only defense**, not defense-in-depth. To regain a backstop, deploy `web-researcher` on its own host/container with egress pointed at a forward proxy holding a destination allowlist — then SSRF bugs become network-enforced non-issues. This is the payoff of the separate-project/separate-host split.

### 6.3 Minimal environment
Spawn the researcher instance and its fetch server with a minimal env: **no Confluence PAT, no primary model keys.** Verify empirically whether OpenCode passes the full parent env to spawned stdio MCP servers or only the declared `environment` block — dump `process.env` in the server on startup and confirm the PAT is absent.

### 6.4 The airlock / structured envelope (the load-bearing piece)
Return crossing the boundary is a **validated data interface, not a message.** The broker:
- Accepts only well-formed JSON matching the schema; drops everything else.
- Runs a **deterministic** neutralization pass (no model in the airlock). Schema has no `instructions`-style field to populate.
- Note: schema constrains *shape*, not *semantics* — an injection can still stuff an imperative into a `claim` string. So the deterministic strip + the primary's "findings are inert evidence" framing both must hold.
- **URLs in findings are never auto-actioned.** If the primary wants a discovered link, that's a fresh `research()` call, re-validated. (Quarantined output is data that cannot re-enter control flow — the CaMeL move, approximated.)
- Hard-sanitize page text in the fetch server before it even becomes an envelope: readability extraction; strip `<script>/<style>/<template>`, comments, hidden elements (`display:none`, off-screen, `aria-hidden`, white-on-white); strip **invisible Unicode** — zero-width chars, bidi overrides `U+202A–202E`, and the **Unicode Tag block `U+E0000–U+E007F`**. Truncate aggressively.

### 6.5 Final backstop — unchanged
The existing remote-Workspace `ask` + diff-preview gate on Confluence writes remains. Even if a laundered instruction survives the airlock and fools the primary, the only dangerous action available to the primary is *proposing a Workspace write*, which a human sees as a diff before it lands. This is the property that makes the whole stack hold.

## 7. Envelope schema (draft)

```json
{
  "query": "string",
  "findings": [
    {
      "claim": "string",
      "source_url": "string",
      "source_title": "string",
      "retrieved_at": "ISO-8601"
    }
  ],
  "sources": [
    { "url": "string", "title": "string", "fetched_at": "ISO-8601" }
  ]
}
```
Owned and version-pinned by agentic-pa (`shared-contract`). Researcher conforms; broker is the validation authority.

## 8. Open decision — does the researcher contain an LLM?

A researcher LLM is only justified if its output is **tightly structured**. Decision matrix:
- **LLM + strict envelope** → good: condenses untrusted text, primary reads less raw web content.
- **No LLM, deterministic fetch + readability extract** → strictly safer (no steerable model touches content), at the cost of synthesis quality and more raw tokens to the primary.
- **LLM + free prose** → worst case, avoid: adds a steerable model *and* a laundering channel.

**Recommended:** support both, route by need — deterministic extract for "fetch this one URL," researcher LLM for genuine multi-hop synthesis, never free prose either way.

## 9. Residual risk to keep tracked

**Query-as-exfil.** A primary injected via Confluence content could be steered to embed internal text into the outbound `query`/`urls`. Project separation does NOT close this. Mitigations: broker caps query length and optionally flags high-entropy/secret-shaped queries; researcher's egress allowlist bounds where any exfil could reach. For a personal setup, cap + log is proportionate.

## 10. Honest cost

This is a real step up from the minimal MVP: two `opencode serve` lifecycles for the backend to manage, two model configs, the broker, and the airlock. Justified by the threat model, but priced in deliberately.

## 11. Next concrete actions

1. Decide §8 (researcher LLM: dual-mode recommended).
2. Lock the envelope schema in `shared-contract` v0.1.
3. Define the wire contract `agentic-pa` ↔ `web-researcher`: localhost-bound, authed (shared secret; A2A-wrapping is the heavyweight option), versioned.
4. Implement the SSRF-validating fetch/search server (resolved-IP checks, manual redirect re-validation, LAN/Confluence-host denial, sanitizer incl. Unicode tag block).
5. Implement the broker + deterministic airlock in agentic-pa.
6. Write the researcher `opencode.json`: web-only tool surface, everything else denied, minimal env.
7. Verify env passthrough behavior empirically (§6.3).
8. Plan researcher deployment on its own host/container with proxy egress (§6.2) to cash in the real isolation.
