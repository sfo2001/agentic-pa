"use strict";
// Stopgap JS-side test harness for frontend/ui/app.js (Node-only, no test
// framework, no jsdom). The repo has zero JS test infrastructure, so this
// file is the lightest thing that actually exercises `checkPendingProposal`
// end-to-end with a minimal DOM + fetch mock, surfaced as a pytest test
// via tests/frontend/test_app_js.py.
//
// Run directly: `node tests/frontend/test_app_js.test.mjs`
// Run via pytest: `pytest tests/frontend/test_app_js.py -q`
//
// Adds 4 cases Agent 2 flagged as the HIGH-2 gap:
//   (a) 404 short-circuits without touching the panel
//   (b) 200 with `{ok:false}` returns silently
//   (c) 200 with a valid proposal populates sweepDiary / sweepActions /
//       sweepTopics and unhides the panel
//   (d) network error does not throw

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
    this.value = "";
    this.hidden = false;
    this.className = "";
    this.children = [];
    this._listeners = {};
  }
  addEventListener(name, fn) { (this._listeners[name] ||= []).push(fn); }
  appendChild(c) { this.children.push(c); c.parent = this; return c; }
  replaceChildren(...kids) { this.children = kids; }
  querySelectorAll(sel) {
    if (sel === "li") return this.children.filter((c) => c.tagName === "li");
    return [];
  }
  get scrollTop() { return 0; }
  set scrollTop(_v) {}
  get scrollHeight() { return 0; }
  setAttribute(k, v) { this[k] = v; }
  getAttribute(k) { return this[k]; }
  // Real HTMLElement.dataset is a live DOMStringMap; the mock returns a
  // plain object whose keys become the element's `data-*` attributes.
  // _renderSweepList writes `cb.dataset.kind = kind` and `cb.dataset.idx`
  // — without this getter that would throw "Cannot set properties of
  // undefined (setting 'kind')".
  get dataset() {
    if (!this._dataset) this._dataset = {};
    return this._dataset;
  }
}

const ELEMENT_IDS = [
  "chat", "composer", "input", "inbox-badge", "upload", "pane-body",
  "pane-header",  // set by showArtifact
  "sweep", "sweep-panel", "sweep-panel-header", "sweep-diary",
  "sweep-actions", "sweep-topics", "sweep-confirm", "sweep-cancel",
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
    querySelectorAll: (_sel) => [],  // app.js line 130 — .action buttons; unused in the test
  },
  setTimeout, clearTimeout, setInterval, clearInterval, console,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// ── Load app.js into the sandbox ──────────────────────────────────────────

const src = readFileSync(APP_JS, "utf-8");
vm.runInContext(src, sandbox, { filename: "app.js" });

const checkPendingProposal = sandbox.checkPendingProposal;
assert.equal(typeof checkPendingProposal, "function",
  "checkPendingProposal must be defined as a top-level function in app.js");

// ── Tests ────────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;
async function test(name, fn) {
  try { await fn(); console.log(`  PASS  ${name}`); passed++; }
  catch (e) { console.error(`  FAIL  ${name}: ${e.message}`); failed++; }
}

function setFetch(handler) { sandbox.fetch = handler; }
// Resets the panel to the "no proposal staged" state (matching the real
// HTML's initial `hidden` attribute and empty textareas) before each test.
// Also clears the in-flight guard, because the load-time call at the bottom
// of app.js (`refreshInbox(); checkPendingProposal();`) is fire-and-forget
// and may still be in flight when the test starts — without the reset the
// second call would short-circuit at the guard and never reach the fetch
// mock we just installed.
function resetEls() {
  for (const e of Object.values(els)) {
    e.hidden = true;
    e.textContent = "";
    e.value = "";
    e.children = [];
  }
  sandbox._proposalCheckInFlight = false;
}

await test("404 short-circuits without touching the panel", async () => {
  resetEls();
  setFetch(async () => ({ status: 404, ok: false, json: async () => ({}) }));
  await checkPendingProposal();
  // sweepPanel stays hidden — only the dedicated 200-ok path unhides it
  assert.equal(els["sweep-panel"].hidden, true,
    "404 must not unhide the review panel");
  assert.equal(els["sweep-diary"].value, "",
    "404 must not populate the diary textarea");
  assert.equal(els["sweep-actions"].children.length, 0,
    "404 must not populate the actions list");
});

await test("{ok:false} returns silently (no panel mutation)", async () => {
  resetEls();
  setFetch(async () => ({ status: 200, ok: true, json: async () => ({ ok: false }) }));
  await checkPendingProposal();
  assert.equal(els["sweep-panel"].hidden, true,
    "{ok:false} must not unhide the review panel");
  assert.equal(els["sweep-diary"].value, "",
    "{ok:false} must not populate the diary textarea");
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
        topics: [],
        meetings: [],
      },
    }),
  }));
  await checkPendingProposal();
  assert.equal(els["sweep-panel"].hidden, false,
    "valid proposal must unhide the review panel");
  assert.equal(els["sweep-diary"].value, "User shared two tasks today.");
  assert.equal(els["sweep-actions"].children.length, 1,
    "valid proposal must render one action <li>");
  assert.equal(els["sweep-panel-header"].textContent, "Proposal to file",
    "MCP-sourced proposal must label the header 'Proposal to file' (not 'Sweep proposal')");
});

await test("network error does not throw", async () => {
  resetEls();
  setFetch(async () => { throw new Error("ECONNREFUSED"); });
  // Must not raise; the catch in checkPendingProposal swallows it and the
  // next turn re-checks.
  await checkPendingProposal();
  assert.equal(els["sweep-panel"].hidden, true,
    "a failed fetch must not unhide the panel");
});

await test("missing proposal field returns silently", async () => {
  resetEls();
  setFetch(async () => ({ status: 200, ok: true, json: async () => ({ ok: true }) }));
  await checkPendingProposal();
  assert.equal(els["sweep-panel"].hidden, true,
    "{ok:true, proposal:undefined} must short-circuit (no panel mutation)");
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
