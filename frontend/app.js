/**
 * app.js — Laravel AI Repair Platform Frontend
 * Vanilla JS. No framework. Wires: CodeMirror, SSE, diff2html, download.
 */

// ── Config ─────────────────────────────────────────────────────────────────────
const API_BASE = "http://localhost:8000";   // ← change if API runs elsewhere

// ── State ──────────────────────────────────────────────────────────────────────
let editor, originalCode = "", repairedCode = "", eventSource = null, completedReceived = false;

// ── Init CodeMirror ────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  editor = CodeMirror.fromTextArea(document.getElementById("code-editor"), {
    mode: "php",
    theme: "dracula",
    lineNumbers: true,
    indentUnit: 4,
    tabSize: 4,
    lineWrapping: false,
    autofocus: true,
  });
  editor.setSize("100%", "100%");

  // Iteration slider
  const slider = document.getElementById("iter-slider");
  const iterVal = document.getElementById("iter-val");
  slider.addEventListener("input", () => { iterVal.textContent = slider.value; });

  // File upload
  document.getElementById("file-upload").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => editor.setValue(ev.target.result);
    reader.readAsText(file);
  });

  // Repair button
  document.getElementById("btn-repair").addEventListener("click", startRepair);

  // Download button
  document.getElementById("btn-download").addEventListener("click", downloadRepaired);

  // History accordion toggle
  document.getElementById("iteration-history").querySelector(".accordion-header")
    .addEventListener("click", function () {
      this.parentElement.classList.toggle("accordion-collapsed");
    });

  // Health check
  checkHealth();
  loadHistory();
});

// ── Health Check ────────────────────────────────────────────────────────────────
async function checkHealth() {
  const badge = document.getElementById("health-badge");
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    const data = await res.json();
    if (data.status === "ok" && data.docker === "connected") {
      badge.textContent = "● Online";
      badge.classList.add("ok");
    } else {
      badge.textContent = `⚠ Docker: ${data.docker}`;
      badge.classList.add("err");
    }
  } catch {
    badge.textContent = "● Offline";
    badge.classList.add("err");
  }
}

// ── Start Repair ────────────────────────────────────────────────────────────────
async function startRepair() {
  const code = editor.getValue();
  if (!code.trim()) return alert("Please paste some PHP code first.");

  originalCode = code;
  repairedCode = "";
  completedReceived = false;

  // Reset UI
  clearLogs();
  document.getElementById("diff-container").innerHTML =
    '<div class="result-placeholder">Running repair...</div>';
  document.getElementById("history-list").innerHTML = "";
  document.getElementById("boost-content").textContent = "Waiting...";
  document.getElementById("btn-download").disabled = true;

  const btn = document.getElementById("btn-repair");
  btn.disabled = true;
  btn.classList.add("running");
  btn.innerHTML = '<span class="btn-icon">⏳</span> Repairing...';

  // POST to /api/repair
  let submissionId;
  try {
    const resp = await fetch(`${API_BASE}/api/repair`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code,
        max_iterations: parseInt(document.getElementById("iter-slider").value),
      }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || "Submission failed");
    }
    const data = await resp.json();
    submissionId = data.submission_id;
    log("info", `📋 Submission ID: ${submissionId}`);
  } catch (err) {
    log("err", `❌ Failed to submit: ${err.message}`);
    resetBtn();
    return;
  }

  // Open SSE stream
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`${API_BASE}/api/repair/${submissionId}/stream`);

  eventSource.onmessage = (e) => handleEvent(JSON.parse(e.data));
  eventSource.onerror = () => {
    // SSE fires onerror when the server closes the stream after 'complete'.
    // Only treat it as a real error if we haven't already received the complete event.
    if (!completedReceived) {
      log("err", "⚠️ SSE stream disconnected. The repair may still be running — check History.");
    }
    eventSource.close();
    resetBtn();
  };
}

// ── Handle SSE Events ───────────────────────────────────────────────────────────
function handleEvent(evt) {
  const { event, data } = evt;

  switch (event) {
    case "iteration_start":
      document.getElementById("current-iter").textContent = data.iteration;
      document.getElementById("max-iter").textContent = data.max;
      log("iter-banner", `── Iteration ${data.iteration} / ${data.max} ──`);
      break;

    case "log_line":
      log("info", data.msg);
      break;

    case "boost_queried":
      const component = data.component_type || "unknown";
      const hasSchema = !!data.schema;
      log("boost", `🔍 Boost — Component: ${component} | Schema: ${hasSchema ? "Detected" : "None"}`);
      document.getElementById("boost-content").textContent = 
        `Laravel Boost Active: [Type: ${component}] [Schema: ${hasSchema ? "LOADED" : "EMPTY"}]`;
      break;

    case "ai_thinking":
      if (data.diagnosis) {
        log("ai", `🤖 Diagnosis: ${data.diagnosis}`);
        log("ai", `🔧 Fix: ${data.fix_description}`);
      } else {
        log("ai", `🤖 ${data.msg || "AI thinking..."}`);
      }
      break;

    case "patch_applied":
      log("ok", `✅ Patch applied [${data.action}]: ${data.fix}`);
      appendIterCard(data);
      break;

    case "pest_result":
      if (data.status === "pass") {
        log("ok", `🧪 Pest: PASSED`);
      } else {
        log("err", `🧪 Pest: FAILED`);
      }
      break;

    case "mutation_result":
      const passed = data.passed;
      const cls = passed ? "ok" : "mut";
      log(cls, `🧬 Mutation score: ${data.score?.toFixed(1)}% (need ${data.threshold}%) — ${passed ? "✅ PASSED" : "⚠️ WEAK"}`);
      break;

    case "complete":
      handleComplete(data);
      break;

    case "error":
      log("err", `❌ ${data.msg}`);
      // Show a persistent banner so errors can't be missed
      showErrorBanner(data.msg);
      break;
  }
}

function showErrorBanner(message) {
  // Remove any existing banner first
  const existing = document.getElementById("error-banner");
  if (existing) existing.remove();

  const banner = document.createElement("div");
  banner.id = "error-banner";
  banner.style.cssText = `
    position: sticky; top: 0; z-index: 999;
    background: linear-gradient(135deg, #dc2626, #991b1b);
    color: #fff; padding: 12px 16px; border-radius: 8px;
    margin: 8px; font-weight: 600; font-size: 14px;
    box-shadow: 0 4px 20px rgba(220,38,38,0.4);
    display: flex; align-items: center; gap: 8px;
    animation: shake 0.5s ease-in-out;
  `;
  banner.innerHTML = `
    <span style="font-size:18px">🚨</span>
    <span style="flex:1">${escHtml(message)}</span>
    <button onclick="this.parentElement.remove()" style="
      background:rgba(255,255,255,0.2); border:none; color:#fff;
      padding:4px 10px; border-radius:4px; cursor:pointer; font-size:12px;
    ">✕</button>
  `;
  const logPanel = document.getElementById("log-output");
  logPanel.prepend(banner);
}

// ── Handle Completion ───────────────────────────────────────────────────────────
function handleComplete(data) {
  completedReceived = true;
  eventSource?.close();
  resetBtn();

  if (data.status === "success") {
    repairedCode = data.final_code;
    log("ok", `🎉 SUCCESS in ${data.iterations} iteration(s)! Mutation: ${data.mutation_score?.toFixed(1)}%`);
    renderDiff(originalCode, repairedCode);
    document.getElementById("btn-download").disabled = false;
    loadHistory();
  } else {
    log("err", `😞 FAILED after ${data.iterations} iterations. ${data.message || ""}`);
    document.getElementById("diff-container").innerHTML =
      '<div class="result-placeholder" style="color:var(--red)">Repair failed. See logs above for the error details.</div>';
    loadHistory();
  }
}

// ── Render Diff ──────────────────────────────────────────────────────────────────
function renderDiff(original, repaired) {
  const diffStr = createUnifiedDiff("original.php", "repaired.php", original, repaired);
  const container = document.getElementById("diff-container");
  container.innerHTML = "";
  new Diff2HtmlUI(container, diffStr, {
    outputFormat: "side-by-side",
    drawFileList: false,
    matching: "lines",
    colorScheme: "dark",
  }).draw();
}

function createUnifiedDiff(oldName, newName, oldStr, newStr) {
  const oldLines = oldStr.split("\n");
  const newLines = newStr.split("\n");
  let diff = `--- ${oldName}\n+++ ${newName}\n@@ -1,${oldLines.length} +1,${newLines.length} @@\n`;
  // Simple line-by-line diff for display purposes
  const maxLen = Math.max(oldLines.length, newLines.length);
  for (let i = 0; i < maxLen; i++) {
    const o = oldLines[i], n = newLines[i];
    if (o === n) { diff += ` ${o ?? ""}\n`; }
    else {
      if (o !== undefined) diff += `-${o}\n`;
      if (n !== undefined) diff += `+${n}\n`;
    }
  }
  return diff;
}

// ── Log Helpers ──────────────────────────────────────────────────────────────────
function log(type, msg) {
  const output = document.getElementById("log-output");
  const placeholder = output.querySelector(".log-placeholder");
  if (placeholder) placeholder.remove();

  const ts = new Date().toLocaleTimeString("en-GB", { hour12: false });
  const div = document.createElement("div");
  div.className = `log-line ${type}`;
  div.innerHTML = `<span class="ts">${ts}</span><span class="msg">${escHtml(msg)}</span>`;
  output.appendChild(div);
  output.scrollTop = output.scrollHeight;
}

function clearLogs() {
  document.getElementById("log-output").innerHTML =
    '<div class="log-placeholder">Starting repair...</div>';
  document.getElementById("current-iter").textContent = "—";
  document.getElementById("max-iter").textContent = "—";
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ── Iteration History Cards ──────────────────────────────────────────────────────
function appendIterCard(data) {
  const list = document.getElementById("history-list");
  const card = document.createElement("div");
  card.className = "iter-card";
  card.innerHTML = `<span class="iter-num">#${document.getElementById("current-iter").textContent}</span>
    — ${escHtml(data.fix || "patch applied")}`;
  list.appendChild(card);
}

// ── Download Repaired Code ────────────────────────────────────────────────────────
function downloadRepaired() {
  if (!repairedCode) return;
  const blob = new Blob([repairedCode], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "repaired_code.php";
  a.click();
  URL.revokeObjectURL(a.href);
}

// ── History Panel ─────────────────────────────────────────────────────────────────
async function loadHistory() {
  try {
    const res = await fetch(`${API_BASE}/api/history`);
    const items = await res.json();
    const el = document.getElementById("history-entries");
    if (!items.length) { el.textContent = "No history yet."; return; }
    el.innerHTML = items.map(item => `
      <div class="iter-card ${item.status}" style="cursor: pointer;" onclick="loadPastSubmission('${item.id}')">
        <span class="iter-num">${item.status === "success" ? "✅" : "❌"}</span>
        ${item.id.slice(0, 8)}… · ${item.total_iterations} iter
        <br><small style="color:var(--text-dim)">${new Date(item.created_at).toLocaleString()}</small>
      </div>`).join("");
  } catch { /* silent */ }
}

async function loadPastSubmission(id) {
  try {
    log("info", `Fetching historical job ${id}...`);
    const res = await fetch(`${API_BASE}/api/history/${id}`);
    if (!res.ok) throw new Error("Could not load past run");
    const data = await res.json();
    
    // Set Editor
    editor.setValue(data.original_code);
    originalCode = data.original_code;
    
    // Update Result Panel
    if (data.status === "success" && data.final_code) {
      repairedCode = data.final_code;
      renderDiff(data.original_code, data.final_code);
      document.getElementById("btn-download").disabled = false;
      log("ok", `Loaded past successful run (${data.total_iterations} iterations).`);
    } else {
      document.getElementById("diff-container").innerHTML =
        '<div class="result-placeholder" style="color:var(--err-color)">Run failed or did not complete.</div>';
      document.getElementById("btn-download").disabled = true;
      log("err", "Loaded past failed run.");
    }
    
    // Update Iteration History List
    const list = document.getElementById("history-list");
    list.innerHTML = "";
    if (data.iterations && data.iterations.length > 0) {
      data.iterations.forEach(it => {
        // Extract fix description from the raw AI response JSON if available
        let fixDesc = "patch applied";
        if (it.ai_response) {
          try {
            const aiData = JSON.parse(it.ai_response);
            fixDesc = aiData.fix_description || fixDesc;
          } catch { /* raw text, not JSON */ }
        }
        const card = document.createElement("div");
        card.className = "iter-card";
        card.innerHTML = `<span class="iter-num">#${it.iteration_num}</span> — ${escHtml(fixDesc)}`;
        list.appendChild(card);
      });

      // Boost Context — pull from the first iteration that has it
      const boostIter = data.iterations.find(it => it.boost_context);
      if (boostIter && boostIter.boost_context) {
        try {
          const boostData = JSON.parse(boostIter.boost_context);
          const parts = [];
          if (boostData.component_type && boostData.component_type !== "unknown") {
            parts.push(`Component: ${boostData.component_type}`);
          }
          if (boostData.schema_info && boostData.schema_info !== "No schema info available.") {
            parts.push(`Schema: ✓`);
          }
          if (boostData.docs_excerpts && boostData.docs_excerpts.length > 0) {
            parts.push(`Docs: ${boostData.docs_excerpts.length} excerpt(s)`);
          }
          document.getElementById("boost-content").textContent = parts.length > 0
            ? parts.join(" | ")
            : "Boost returned empty context.";
        } catch {
          document.getElementById("boost-content").textContent = boostIter.boost_context;
        }
      } else {
        document.getElementById("boost-content").textContent = "No Boost context was used.";
      }
    }
    
  } catch (err) {
    log("err", err.message);
  }
}

// ── Reset Button ──────────────────────────────────────────────────────────────────
function resetBtn() {
  const btn = document.getElementById("btn-repair");
  btn.disabled = false;
  btn.classList.remove("running");
  btn.innerHTML = '<span class="btn-icon">🔧</span> Repair Code';
}
