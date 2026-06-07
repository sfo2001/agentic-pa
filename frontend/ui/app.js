"use strict";
const chat = document.getElementById("chat");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const badge = document.getElementById("inbox-badge");
const upload = document.getElementById("upload");
const paneBody = document.getElementById("pane-body");
// Linkify BACKTICK-delimited workspace paths so names with spaces/commas/unicode
// (e.g. `documents/KI-Gefahren, Architekturen und MSA-LLM.md`) are clickable.
// Group 1 = the path (without backticks). The agent writes paths in backticks.
const PATH_RE = /`((?:inbox|meetings|topics|briefs|documents|archive)\/[^`]+?\.(?:md|markdown|txt))`/g;

async function showArtifact(path) {
  try {
    const r = await fetch("/api/file?path=" + encodeURIComponent(path));
    const j = await r.json();
    if (!r.ok) { paneBody.textContent = `Could not open ${path}: ${j.error || r.status}`; return; }
    document.getElementById("pane-header").textContent = j.path;
    if (j.html !== null && j.html !== undefined) { paneBody.innerHTML = j.html; } // server-sanitized HTML
    else { paneBody.textContent = j.text || ""; }                                  // non-markdown: plain text
  } catch (_) { paneBody.textContent = `Network error opening ${path}.`; }
}

function addMsg(kind, text) {
  const el = document.createElement("div");
  el.className = "msg " + kind;
  if (kind === "assistant" || kind === "user") {
    let last = 0; const frag = document.createDocumentFragment();
    text.replace(PATH_RE, (full, path, idx) => {
      if (path.includes("..")) {                       // never linkify traversal paths
        frag.appendChild(document.createTextNode(text.slice(last, idx + full.length)));
        last = idx + full.length; return full;
      }
      frag.appendChild(document.createTextNode(text.slice(last, idx)));
      const a = document.createElement("a"); a.href = "#"; a.textContent = path; a.className = "artifact-link";
      a.addEventListener("click", (e) => { e.preventDefault(); showArtifact(path); });
      frag.appendChild(a); last = idx + full.length; return full;
    });
    frag.appendChild(document.createTextNode(text.slice(last)));
    el.appendChild(frag);
  } else {
    el.textContent = text;
  }
  chat.appendChild(el); chat.scrollTop = chat.scrollHeight; return el;
}
function addTool(name, status) {
  const el = document.createElement("div");
  el.className = "tool";
  el.textContent = `🔧 ${name} — ${status}`;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}
// Collapsible "Thinking" block for the model's reasoning trace (collapsed by default).
function addThinking() {
  const d = document.createElement("details");
  d.className = "thinking";
  const s = document.createElement("summary");
  s.textContent = "Thinking…";
  const body = document.createElement("div");
  body.className = "thinking-body";          // textContent only — never HTML
  d.appendChild(s);
  d.appendChild(body);
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return body;
}
function setBusy(b) { composer.setAttribute("aria-disabled", b ? "true" : "false"); }

async function refreshInbox() {
  try {
    const r = await fetch("/api/inbox");
    const { count } = await r.json();
    badge.hidden = count === 0;
    badge.textContent = `${count} new`;
  } catch (_) { /* non-fatal */ }
}

// One turn: open SSE first, then POST the message; render until `done`.
function runTurn(text) {
  setBusy(true);
  addMsg("user", text);
  let bubble = null;
  let thinking = null;
  const es = new EventSource("/api/events");
  const finish = () => { es.close(); setBusy(false); refreshInbox(); checkPendingProposal(); };

  es.onopen = () => {
    fetch("/api/message", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text }),
    }).then((r) => {
      if (!r.ok) { addMsg("system", "Could not start the turn (session lost)."); finish(); }
    }).catch(() => { addMsg("system", "Network error."); finish(); });
  };

  es.onmessage = (e) => {
    let evt;
    try { evt = JSON.parse(e.data); } catch (_) { return; }
    if (evt.type === "message_delta") {
      if (!bubble) bubble = addMsg("assistant", "");
      bubble.textContent += evt.text;
      chat.scrollTop = chat.scrollHeight;
    } else if (evt.type === "reasoning_delta") {
      if (!thinking) thinking = addThinking();
      thinking.textContent += evt.text;
      chat.scrollTop = chat.scrollHeight;
    } else if (evt.type === "tool_call") {
      addTool(evt.name, evt.status);
    } else if (evt.type === "present") {
      showArtifact(evt.path);
    } else if (evt.type === "error") {
      addMsg("system", `Error (${evt.kind}): ${evt.message}`);
      finish();
    } else if (evt.type === "done") {
      finish();
    }
  };
  es.onerror = () => { addMsg("system", "Connection lost."); finish(); };
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || composer.getAttribute("aria-disabled") === "true") return;
  input.value = "";
  runTurn(text);
});

document.querySelectorAll(".action").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (composer.getAttribute("aria-disabled") === "true") return;
    if (btn.dataset.sweep === "true") { runSweep(); return; }
    runTurn(btn.dataset.prompt);
  });
});

upload.addEventListener("change", async () => {
  const file = upload.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  addMsg("system", `Uploading ${file.name}…`);
  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await r.json();
    if (r.ok) addMsg("system", `Stored ${j.stored}${j.markdown ? " (+ Markdown)" : ""}.`);
    else addMsg("system", `Upload failed: ${j.error || r.status}.`);
  } catch (_) { addMsg("system", "Upload network error."); }
  upload.value = "";
});

const undoBtn = document.getElementById("undo");
undoBtn.addEventListener("click", async () => {
  if (composer.getAttribute("aria-disabled") === "true") return;
  try {
    const r = await fetch("/api/undo", { method: "POST" });
    const j = await r.json();
    if (r.ok) addMsg("system", `Undid the last change (${j.reverted.slice(0, 7)}).`);
    else addMsg("system", `Nothing to undo.`);
  } catch (_) { addMsg("system", "Undo network error."); }
  refreshInbox();
});

// ── Sweep: review a structured proposal, then confirm to apply ────────────────
const sweepBtn = document.getElementById("sweep");
const sweepPanel = document.getElementById("sweep-panel");
const sweepPanelHeader = document.getElementById("sweep-panel-header");
const sweepDiary = document.getElementById("sweep-diary");
const sweepActions = document.getElementById("sweep-actions");
const sweepTopics = document.getElementById("sweep-topics");
const sweepConfirm = document.getElementById("sweep-confirm");
const sweepCancel = document.getElementById("sweep-cancel");
// Wrap in an object so the reference itself is `const` (the slot is
// reassigned by setSweepContext/clearSweepContext, not the variable).
// `{proposal, capture?, session?, last_id?, mcp?}` — `mcp: true` marks an
// agent-staged proposal (the one the user is asked to file); otherwise
// it's a Sweep flow. The header text is derived from this flag so the
// two flows can't overwrite each other's label.
const sweepContext = { current: null };
const setSweepContext = (ctx) => {
  sweepContext.current = ctx;
  // Header text is a function of the proposal's source (MCP vs Sweep), not
  // a side effect of each render — set here so a chat-driven MCP proposal
  // landing while a Sweep is in-flight (or vice versa) cannot clobber the
  // visible label.
  sweepPanelHeader.textContent = ctx && ctx.mcp ? "Proposal to file" : "Sweep proposal";
};
const clearSweepContext = () => {
  sweepContext.current = null;
  sweepPanelHeader.textContent = "";  // reset so the next setSweepContext wins
};

function _clearSweepPanel() {
  sweepDiary.value = "";
  sweepActions.replaceChildren();
  sweepTopics.replaceChildren();
}

function _renderSweepList(ul, items, kind) {
  items.forEach((item, idx) => {
    const li = document.createElement("li");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.dataset.kind = kind;
    cb.dataset.idx = String(idx);
    const label = document.createElement("label");
    if (kind === "action") {
      label.textContent = item;
    } else {
      // topic entry: {slug, section, text}
      label.textContent = `[${item.slug || "?"}] ${item.section || "## Current state"} — ${item.text || ""}`;
    }
    li.appendChild(cb);
    li.appendChild(label);
    ul.appendChild(li);
  });
}

async function runSweep() {
  if (composer.getAttribute("aria-disabled") === "true") return;
  setBusy(true);
  try {
    const r = await fetch("/api/sweep/prep", { method: "POST" });
    const j = await r.json();
    if (!r.ok || !j.ok) {
      addMsg("system", `Sweep prep failed: ${j.error || r.status}`);
      return;
    }
    if (!j.capture) {
      addMsg("system", "Nothing new to sweep.");
      return;
    }
    setSweepContext({ capture: j.capture, session: j.session, last_id: j.last_id });
    runTurn(`Ingest the file inbox/${j.capture} in PROPOSE mode via present_propose`);
  } catch (_) {
    addMsg("system", "Sweep prep network error.");
  } finally {
    setBusy(false);
  }
}

sweepBtn.addEventListener("click", runSweep);

sweepCancel.addEventListener("click", () => {
  sweepPanel.hidden = true;
  clearSweepContext();
});

sweepConfirm.addEventListener("click", async () => {
  const ctx = sweepContext.current;
  if (!ctx) return;
  sweepPanel.hidden = true;
  setBusy(true);
  try {
    const body = {};
    if (ctx.session && ctx.last_id) {
      body.session = ctx.session;
      body.last_id = ctx.last_id;
    }
    if (ctx.capture) {
      body.capture = ctx.capture;
    }
    const hasBody = Object.keys(body).length > 0;
    const r = await fetch("/api/proposal/confirm", {
      method: "POST",
      headers: hasBody ? { "content-type": "application/json" } : {},
      body: hasBody ? JSON.stringify(body) : undefined,
    });
    const j = await r.json();
    if (r.ok && j.ok) {
      const a = j.applied || {};
      addMsg("system", `Filed: diary=${a.diary ? 1 : 0}, +${a.actions || 0} actions, +${a.topics || 0} topic edits, +${a.meetings || 0} meetings.`);
    } else {
      addMsg("system", `Confirm failed: ${j.error || r.status}`);
    }
  } catch (_) {
    addMsg("system", "Confirm network error.");
  } finally {
    setBusy(false);
    clearSweepContext();
  }
});

// ── MCP proposal: the agent's present_propose stages inbox/_proposal.json.
// Surface it in the same review panel (on load and on the done/error of each
// turn) and confirm via /api/proposal/confirm. Without this the staged
// proposal is invisible — present_propose "completes" but nothing actionable
// appears in the UI.
//
// Concurrency: an in-flight guard prevents two overlapping polls from
// interleaving. With the SSE-event-source-per-turn design, two rapid user
// messages can produce overlapping `finish()` paths, each starting a
// fetch("/api/proposal"). The second call is skipped (a no-op), so the panel
// reflects whichever response arrives first — and re-rendering the same
// content is idempotent.
let _proposalCheckInFlight = false;
async function checkPendingProposal() {
  if (_proposalCheckInFlight) return;
  _proposalCheckInFlight = true;
  try {
    const r = await fetch("/api/proposal");
    if (r.status === 404) return;            // nothing staged — the common case
    const j = await r.json();
    if (!r.ok || !j.ok || !j.proposal) return;
    _clearSweepPanel();
    // Preserve sweep metadata (capture, session, last_id) if set by runSweep.
    const existing = sweepContext.current || {};
    setSweepContext({
      proposal: j.proposal,
      capture: existing.capture || null,
      session: existing.session || null,
      last_id: existing.last_id || null,
    });
    sweepPanelHeader.textContent = "Proposal to file";
    sweepDiary.value = j.proposal.diary || "";
    _renderSweepList(sweepActions, j.proposal.actions || [], "action");
    _renderSweepList(sweepTopics, j.proposal.topics || [], "topic");
    sweepPanel.hidden = false;
  } catch (_) { /* transient; the next turn re-checks */ }
  finally { _proposalCheckInFlight = false; }
}

refreshInbox();
checkPendingProposal();
