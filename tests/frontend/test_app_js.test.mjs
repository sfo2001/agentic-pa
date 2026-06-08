"use strict";
// Node-only test harness for frontend/ui/app.js (no test framework, no jsdom).
// The repo has zero JS test infrastructure, so this file is the lightest thing
// that exercises the client logic with a minimal DOM + fetch mock, surfaced as
// a pytest test via tests/frontend/test_app_js.py.
//
// Run directly: `node tests/frontend/test_app_js.test.mjs`
// Run via pytest: `pytest tests/frontend/test_app_js.py -q`
//
// Covers the SSR-islands client surface:
//   • checkPendingProposal — the staged-proposal review panel (404 / {ok:false}
//     / valid / network error / missing field)
//   • humanizeTaskOp
//   • switchTab — artifact empty state, server-fragment swap, fetch error
//   • showArtifact — sanitized-html branch, raw-text-as-textContent (XSS guard),
//     error sink uses textContent
//   • paneBody [data-op] delegation — success swap, failure surfaced via addMsg

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_JS = resolve(HERE, "..", "..", "frontend", "ui", "app.js");

// ── Minimal DOM + globals the app.js top-level expects ────────────────────

class Element {
  constructor(id = "") {
    this.id = id;
    this.tagName = "div";
    this.textContent = "";
    this.innerHTML = "";
    this.value = "";
    this.hidden = false;
    this.className = "";
    this.children = [];
    this._listeners = {};
  }
  addEventListener(name, fn) { (this._listeners[name] ||= []).push(fn); }
  dispatch(name, ev) { (this._listeners[name] || []).forEach((fn) => fn(ev)); }
  appendChild(c) { this.children.push(c); c.parent = this; return c; }
  replaceChildren(...kids) { this.children = kids; }
  querySelectorAll(sel) {
    if (sel === "li") return this.children.filter((c) => c.tagName === "li");
    return [];
  }
  closest() { return null; }
  classList = { toggle() {}, add() {}, remove() {} };
  get scrollTop() { return 0; }
  set scrollTop(_v) {}
  get scrollHeight() { return 0; }
  setAttribute(k, v) { this[k] = v; }
  getAttribute(k) { return this[k]; }
  // Real HTMLElement.dataset is a live DOMStringMap; the mock returns a
  // plain object whose keys become the element's `data-*` attributes.
  get dataset() {
    if (!this._dataset) this._dataset = {};
    return this._dataset;
  }
}

const ELEMENT_IDS = [
  "chat", "composer", "input", "inbox-badge", "upload", "pane-body",
  "pane-header",  // set by showArtifact
  "sweep", "sweep-panel", "sweep-panel-header", "sweep-diary",
  "sweep-actions", "sweep-topics", "sweep-task-ops", "sweep-confirm", "sweep-cancel",
  "undo",
];
const els = Object.fromEntries(ELEMENT_IDS.map((id) => [id, new Element(id)]));

const sandbox = {
  fetch: async () => ({ status: 404, ok: false, json: async () => ({}) }),
  EventSource: class { constructor() {} close() {} },
  document: {
    getElementById: (id) => els[id] ?? null,
    createElement: (tag) => {
      const e = new Element();
      e.tagName = tag.toUpperCase();
      return e;
    },
    createDocumentFragment: () => new Element("frag"),
    createTextNode: (text) => ({ textContent: text, appendChild() {}, parent: null }),
    querySelectorAll: (_sel) => [],  // .pane-tab / .action buttons — unused here
  },
  setTimeout, clearTimeout, setInterval, clearInterval, console,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// ── Load app.js into the sandbox ──────────────────────────────────────────

const src = readFileSync(APP_JS, "utf-8");
vm.runInContext(src, sandbox, { filename: "app.js" });

const checkPendingProposal = sandbox.checkPendingProposal;
const humanizeTaskOp = sandbox.humanizeTaskOp;
const switchTab = sandbox.switchTab;
const showArtifact = sandbox.showArtifact;
assert.equal(typeof checkPendingProposal, "function",
  "checkPendingProposal must be a top-level function in app.js");
assert.equal(typeof humanizeTaskOp, "function",
  "humanizeTaskOp must be a top-level function in app.js");
assert.equal(typeof switchTab, "function",
  "switchTab must be a top-level function in app.js");
assert.equal(typeof showArtifact, "function",
  "showArtifact must be a top-level function in app.js");

// ── Harness ────────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log(`  PASS  ${name}`); passed++; }
  catch (e) { console.error(`  FAIL  ${name}: ${e.message}`); failed++; }
}
const flush = () => new Promise((res) => setTimeout(res, 0));
function setFetch(handler) { sandbox.fetch = handler; }
function resetEls() {
  for (const e of Object.values(els)) {
    e.hidden = true;
    e.textContent = "";
    e.innerHTML = "";
    e.value = "";
    e.children = [];
  }
  sandbox._proposalCheckInFlight = false;
}

// ── checkPendingProposal ─────────────────────────────────────────────────

await test("404 short-circuits without touching the panel", async () => {
  resetEls();
  setFetch(async () => ({ status: 404, ok: false, json: async () => ({}) }));
  await checkPendingProposal();
  assert.equal(els["sweep-panel"].hidden, true, "404 must not unhide the review panel");
  assert.equal(els["sweep-diary"].value, "", "404 must not populate the diary textarea");
  assert.equal(els["sweep-actions"].children.length, 0, "404 must not populate the actions list");
});

await test("{ok:false} returns silently (no panel mutation)", async () => {
  resetEls();
  setFetch(async () => ({ status: 200, ok: true, json: async () => ({ ok: false }) }));
  await checkPendingProposal();
  assert.equal(els["sweep-panel"].hidden, true, "{ok:false} must not unhide the review panel");
  assert.equal(els["sweep-diary"].value, "", "{ok:false} must not populate the diary textarea");
});

await test("valid proposal populates panel + sets MCP header label", async () => {
  resetEls();
  setFetch(async () => ({
    status: 200, ok: true,
    json: async () => ({
      ok: true,
      proposal: {
        diary: "User shared two tasks today.",
        actions: ["(A) Prepare org chart +presentation due:2026-06-09 upd:2026-06-05"],
        topics: [], meetings: [],
      },
    }),
  }));
  await checkPendingProposal();
  assert.equal(els["sweep-panel"].hidden, false, "valid proposal must unhide the review panel");
  assert.equal(els["sweep-diary"].value, "User shared two tasks today.");
  assert.equal(els["sweep-actions"].children.length, 1, "valid proposal must render one action <li>");
  assert.equal(els["sweep-panel-header"].textContent, "Proposal to file",
    "MCP-sourced proposal must label the header 'Proposal to file'");
});

await test("network error does not throw", async () => {
  resetEls();
  setFetch(async () => { throw new Error("ECONNREFUSED"); });
  await checkPendingProposal();
  assert.equal(els["sweep-panel"].hidden, true, "a failed fetch must not unhide the panel");
});

await test("missing proposal field returns silently", async () => {
  resetEls();
  setFetch(async () => ({ status: 200, ok: true, json: async () => ({ ok: true }) }));
  await checkPendingProposal();
  assert.equal(els["sweep-panel"].hidden, true,
    "{ok:true, proposal:undefined} must short-circuit (no panel mutation)");
});

// ── humanizeTaskOp ───────────────────────────────────────────────────────

await test("humanizeTaskOp renders description + verb (+value)", () => {
  const a = { text: "Sign off Atlas design", id: "abc123" };
  assert.strictEqual(humanizeTaskOp(a, "complete", null), "Sign off Atlas design  →  complete");
  assert.strictEqual(humanizeTaskOp(a, "reprioritize", "A"), "Sign off Atlas design  →  reprioritize (A)");
});

// ── switchTab ────────────────────────────────────────────────────────────

await test("switchTab('artifact') shows the empty state without fetching", async () => {
  resetEls();
  let fetched = false;
  setFetch(async () => { fetched = true; return { ok: true, text: async () => "" }; });
  switchTab("artifact");
  await flush();
  assert.equal(fetched, false, "artifact tab must not hit the network");
  assert.ok(els["pane-body"].innerHTML.includes("Nothing presented yet"),
    "artifact tab must render the empty state");
});

await test("switchTab('actions') swaps in the server fragment", async () => {
  resetEls();
  setFetch(async () => ({ ok: true, status: 200, text: async () => '<div class="bucket">X</div>' }));
  switchTab("actions");
  await flush(); await flush();
  assert.equal(els["pane-body"].innerHTML, '<div class="bucket">X</div>',
    "actions tab must swap in the /api/pane/actions fragment");
});

await test("switchTab fetch error shows 'Could not load pane.'", async () => {
  resetEls();
  setFetch(async () => { throw new Error("boom"); });
  switchTab("diary");
  await flush(); await flush();
  assert.ok(els["pane-body"].innerHTML.includes("Could not load pane"),
    "a failed pane fetch must show the error state");
});

// ── showArtifact ─────────────────────────────────────────────────────────

await test("showArtifact renders sanitized html via innerHTML", async () => {
  resetEls();
  setFetch(async () => ({
    ok: true, status: 200,
    json: async () => ({ path: "documents/note.md", html: "<h1>Hi</h1>", text: null }),
  }));
  await showArtifact("documents/note.md");
  assert.ok(els["pane-body"].innerHTML.includes("<h1>Hi</h1>"), "markdown html must render");
  assert.equal(els["pane-header"].textContent, "documents/note.md");
});

await test("showArtifact renders raw text as textContent (XSS guard)", async () => {
  resetEls();
  const payload = '<img src=x onerror="alert(1)">';
  setFetch(async () => ({
    ok: true, status: 200,
    json: async () => ({ path: "documents/evil.txt", html: null, text: payload }),
  }));
  await showArtifact("documents/evil.txt");
  assert.equal(els["pane-body"].textContent, payload,
    "non-markdown file text must be assigned to textContent verbatim");
  assert.ok(!String(els["pane-body"].innerHTML).includes("<img"),
    "raw file text must NEVER reach innerHTML (XSS regression guard)");
});

await test("showArtifact error sink uses textContent (no html sink)", async () => {
  resetEls();
  setFetch(async () => ({ ok: false, status: 404, json: async () => ({ error: "not found" }) }));
  await showArtifact("documents/missing.md");
  assert.ok(els["pane-body"].textContent.includes("Could not open"),
    "error must be surfaced via textContent");
  assert.ok(!String(els["pane-body"].innerHTML).includes("Could not open"),
    "error path must not interpolate the path into an html sink");
});

// ── paneBody [data-op] click delegation ──────────────────────────────────

function makeOpBtn(id, op, value) {
  const b = new Element();
  b._dataset = { id, op, value };
  b.closest = (sel) => (sel === "[data-op]" ? b : null);
  return b;
}
async function clickOp(btn) {
  els["pane-body"].dispatch("click", { target: btn });
  await flush(); await flush();
}

await test("[data-op] success swaps in the re-rendered actions fragment", async () => {
  resetEls();
  setFetch(async () => ({ ok: true, status: 200, text: async () => '<div class="bucket">done</div>' }));
  await clickOp(makeOpBtn("id0001", "complete", ""));
  assert.ok(els["pane-body"].innerHTML.includes('class="bucket"'),
    "a successful task-op must swap in the server-rendered actions fragment");
});

await test("[data-op] failure is surfaced via addMsg, panel left intact", async () => {
  resetEls();
  els["pane-body"].innerHTML = "<keep>";
  let msg = "";
  sandbox.addMsg = (_kind, text) => { msg = text; };
  setFetch(async () => ({ ok: false, status: 400, text: async () => "Task op failed: malformed id" }));
  await clickOp(makeOpBtn("bad id", "complete", ""));
  assert.ok(msg.includes("Task op failed"), "a 400 must report the error via addMsg");
  assert.equal(els["pane-body"].innerHTML, "<keep>",
    "a failed task-op must not clobber the pane body");
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
