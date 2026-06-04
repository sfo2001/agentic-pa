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
  const finish = () => { es.close(); setBusy(false); refreshInbox(); };

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
const sweepDiary = document.getElementById("sweep-diary");
const sweepActions = document.getElementById("sweep-actions");
const sweepTopics = document.getElementById("sweep-topics");
const sweepConfirm = document.getElementById("sweep-confirm");
const sweepCancel = document.getElementById("sweep-cancel");
// Wrap in an object so the reference itself is `const` (the slot is
// reassigned by setSweepContext/clearSweepContext, not the variable).
const sweepContext = { current: null };  // {proposal, capture, session, last_id}
const setSweepContext = (ctx) => { sweepContext.current = ctx; };
const clearSweepContext = () => { sweepContext.current = null; };

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
  _clearSweepPanel();
  try {
    const r = await fetch("/api/sweep", { method: "POST" });
    const j = await r.json();
    if (!r.ok || !j.ok) {
      addMsg("system", `Sweep failed: ${j.error || r.status}`);
      return;
    }
    if (!j.proposal) {
      addMsg("system", "Nothing new to sweep.");
      return;
    }
    setSweepContext({ proposal: j.proposal, capture: j.capture, session: j.session, last_id: j.last_id });
    sweepDiary.value = j.proposal.diary || "";
    _renderSweepList(sweepActions, j.proposal.actions || [], "action");
    _renderSweepList(sweepTopics, j.proposal.topics || [], "topic");
    sweepPanel.hidden = false;
  } catch (_) {
    addMsg("system", "Sweep network error.");
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
  // Build the edited proposal from the panel's current state.
  const diary = sweepDiary.value;
  const actions = [];
  sweepActions.querySelectorAll("li").forEach((li) => {
    const cb = li.querySelector("input");
    if (cb.checked) actions.push(li.querySelector("label").textContent);
  });
  const topics = [];
  sweepTopics.querySelectorAll("li").forEach((li) => {
    const cb = li.querySelector("input");
    if (!cb.checked) return;
    const orig = ctx.proposal.topics[Number(cb.dataset.idx)];
    topics.push(orig);
  });
  const edited = {
    proposal: { diary, actions, topics, meetings: ctx.proposal.meetings || [] },
    capture: ctx.capture,
    session: ctx.session,
    last_id: ctx.last_id,
  };
  sweepPanel.hidden = true;
  setBusy(true);
  try {
    const r = await fetch("/api/sweep/confirm", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(edited),
    });
    const j = await r.json();
    if (r.ok && j.ok) {
      const a = j.applied || {};
      addMsg("system", `Sweep applied: diary=${a.diary ? 1 : 0}, +${a.actions || 0} actions, +${a.topics || 0} topic edits, +${a.meetings || 0} meetings.`);
    } else {
      addMsg("system", `Sweep confirm failed: ${j.error || r.status}`);
    }
  } catch (_) {
    addMsg("system", "Sweep confirm network error.");
  } finally {
    setBusy(false);
    clearSweepContext();
  }
});

refreshInbox();
