/**
 * Run History — Sidebar section showing past runs from persistent storage.
 *
 * Fetches runs from /api/runs and renders them in the sidebar.
 * Clicking a run opens it in Replay mode.
 */

let container = null;
let storageEnabled = false;
let runs = [];
let onReplayRun = null;  // callback(runId) — set by dashboard.js

export function init(replayCallback) {
  container = document.getElementById("run-history");
  onReplayRun = replayCallback || null;

  const refreshBtn = document.getElementById("refresh-runs");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => loadRuns());
  }

  // Initial load
  loadRuns();
}

export async function loadRuns() {
  if (!container) return;
  container.innerHTML = '<div class="run-history__loading">Loading...</div>';

  try {
    const resp = await fetch("/api/runs?limit=20");
    const data = await resp.json();

    storageEnabled = data.storage_enabled !== false;
    if (!storageEnabled) {
      container.innerHTML = '<div class="run-history__empty">Storage not enabled</div>';
      return;
    }

    runs = data.runs || [];
    _render();
  } catch {
    container.innerHTML = '<div class="run-history__empty">Failed to load runs</div>';
  }
}

function _render() {
  if (!runs.length) {
    container.innerHTML = '<div class="run-history__empty">No runs recorded yet</div>';
    return;
  }

  container.innerHTML = runs.map(run => {
    const statusClass = `run-item__status--${run.status || "unknown"}`;
    const cost = run.total_cost != null ? `$${run.total_cost.toFixed(4)}` : "";
    const time = _fmtDate(run.started_at);
    const duration = _fmtDuration(run.started_at, run.completed_at);
    const eventCount = run.event_count || 0;
    const agentCount = run.agent_count || 0;

    return `<div class="run-item" data-run-id="${_esc(run.id)}">
      <div class="run-item__header">
        <span class="run-item__name">${_esc(run.name || "Unnamed Run")}</span>
        <span class="run-item__status ${statusClass}">${_esc(run.status)}</span>
      </div>
      <div class="run-item__meta">
        <span>${time}</span>
        ${duration ? `<span>${duration}</span>` : ""}
        ${cost ? `<span>${cost}</span>` : ""}
      </div>
      <div class="run-item__meta">
        <span>${agentCount} agent${agentCount !== 1 ? "s" : ""}</span>
        <span>${eventCount} event${eventCount !== 1 ? "s" : ""}</span>
      </div>
      <div class="run-item__actions">
        <button class="run-item__btn run-item__btn--replay" data-action="replay" title="Replay">&#x25B6; Replay</button>
        <button class="run-item__btn run-item__btn--export" data-action="export" title="Export JSON">&#x2B73; Export</button>
        <button class="run-item__btn run-item__btn--delete" data-action="delete" title="Delete">&#x2715;</button>
      </div>
    </div>`;
  }).join("");

  // Bind click handlers
  container.querySelectorAll(".run-item__btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const runId = btn.closest("[data-run-id]").dataset.runId;
      const action = btn.dataset.action;
      if (action === "replay" && onReplayRun) onReplayRun(runId);
      if (action === "export") _exportRun(runId);
      if (action === "delete") _deleteRun(runId);
    });
  });

  // Click run row to replay
  container.querySelectorAll(".run-item").forEach(item => {
    item.addEventListener("click", () => {
      const runId = item.dataset.runId;
      if (onReplayRun) onReplayRun(runId);
    });
  });
}

async function _exportRun(runId) {
  try {
    const resp = await fetch(`/api/runs/${encodeURIComponent(runId)}/export`);
    if (!resp.ok) throw new Error("Export failed");
    const data = await resp.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `pixelpulse-run-${runId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error("[RunHistory] Export failed:", err);
  }
}

async function _deleteRun(runId) {
  if (!confirm("Delete this run and all its events?")) return;
  try {
    const resp = await fetch(`/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
    if (resp.ok) {
      runs = runs.filter(r => r.id !== runId);
      _render();
    }
  } catch (err) {
    console.error("[RunHistory] Delete failed:", err);
  }
}

function _fmtDate(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    return d.toLocaleDateString([], { month: "short", day: "numeric" }) +
      " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch { return ts; }
}

function _fmtDuration(start, end) {
  if (!start || !end) return "";
  try {
    const ms = new Date(end) - new Date(start);
    if (ms < 0) return "";
    if (ms < 60000) return `${(ms / 1000).toFixed(0)}s`;
    if (ms < 3600000) return `${(ms / 60000).toFixed(1)}m`;
    return `${(ms / 3600000).toFixed(1)}h`;
  } catch { return ""; }
}

function _esc(s) {
  if (!s) return "";
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
