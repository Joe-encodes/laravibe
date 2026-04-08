/**
 * app.js — Laravel AI Repair Platform Frontend
 * Vanilla JS. No framework. Wires: CodeMirror, SSE, diff2html, download.
 */

// ── Config ─────────────────────────────────────────────────────────────────────
const API_BASE = "http://localhost:8000";   // ← change if API runs elsewhere

// ── State ──────────────────────────────────────────────────────────────────────
let editor, originalCode = "", repairedCode = "", eventSource = null;

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
    log("err", "SSE connection lost.");
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
      log("boost", `🔍 Boost queried — component: ${data.component_type || "?"}`);
      if (data.schema) {
        document.getElementById("boost-content").textContent =
          `Component: ${data.component_type} | Schema: ${data.schema ? "✓" : "✗"}`;
      }
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
      log("err", `❌ Error: ${data.msg}`);
      resetBtn();
      eventSource?.close();
      break;
  }
}

// ── Handle Completion ───────────────────────────────────────────────────────────
function handleComplete(data) {
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
      '<div class="result-placeholder" style="color:var(--red)">Repair failed. See logs for details.</div>';
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
      <div class="iter-card ${item.status}">
        <span class="iter-num">${item.status === "success" ? "✅" : "❌"}</span>
        ${item.id.slice(0, 8)}… · ${item.total_iterations} iter
        <br><small style="color:var(--text-dim)">${new Date(item.created_at).toLocaleString()}</small>
      </div>`).join("");
  } catch { /* silent */ }
}

// ── Reset Button ──────────────────────────────────────────────────────────────────
function resetBtn() {
  const btn = document.getElementById("btn-repair");
  btn.disabled = false;
  btn.classList.remove("running");
  btn.innerHTML = '<span class="btn-icon">🔧</span> Repair Code';
}
