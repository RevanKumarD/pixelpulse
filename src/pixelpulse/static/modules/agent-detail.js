/**
 * Enhanced Agent Detail Panel — "Chrome DevTools for agents"
 *
 * Full-height right panel with 4 tabs: Overview, Messages, Reasoning, Performance.
 * Fetches data from both in-memory state and REST API (when storage is enabled).
 */
import {
  getAgent, AGENT_ROLES, TEAMS, getEventsForAgent, getCostForAgent,
  getComms, subscribe,
} from "./state.js";

let panel, currentAgent = null;
let activeTab = "overview";
let apiStats = null;       // Fetched from /api/agents/{id}/stats
let apiEvents = null;      // Fetched from /api/agents/{id}/events
let storageEnabled = false;

export function init() {
  panel = document.getElementById("agent-detail");
  if (!panel) return;

  // Tab switching
  panel.querySelectorAll(".agent-detail__tab").forEach(btn => {
    btn.addEventListener("click", () => _switchTab(btn.dataset.tab));
  });

  panel.querySelector(".agent-detail__close")
    .addEventListener("click", close);

  // Listen for canvas agent clicks
  const canvas = document.getElementById("office-canvas");
  if (canvas) {
    canvas.addEventListener("agent-click", (e) => {
      openAgent(e.detail.agentName);
    });
  }

  // Listen for sidebar agent clicks (delegated)
  const activity = document.getElementById("agent-activity");
  if (activity) {
    activity.addEventListener("click", (e) => {
      const row = e.target.closest("[data-agent]");
      if (row) openAgent(row.dataset.agent);
    });
  }

  // Close on Esc
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden) close();
  });

  // Close on click outside
  document.addEventListener("click", (e) => {
    if (!panel.hidden
        && !panel.contains(e.target)
        && !e.target.closest("canvas")
        && !e.target.closest("[data-agent]")) {
      close();
    }
  });

  // Message filters
  const dirFilter = document.getElementById("msg-direction-filter");
  const msgSearch = document.getElementById("msg-search");
  if (dirFilter) dirFilter.addEventListener("change", () => _renderMessages());
  if (msgSearch) msgSearch.addEventListener("input", () => _renderMessages());

  // Reasoning search
  const reasonSearch = document.getElementById("reasoning-search");
  if (reasonSearch) reasonSearch.addEventListener("input", () => _renderReasoning());

  // Subscribe to state changes for live updates
  subscribe((changeType) => {
    if (!panel.hidden && currentAgent) {
      if (["agent", "cost", "event", "comm", "bubble"].includes(changeType)) {
        _renderActiveTab();
      }
    }
  });

  // Check if storage is enabled
  _checkStorage();
}

async function _checkStorage() {
  try {
    const resp = await fetch("/api/runs");
    const data = await resp.json();
    storageEnabled = data.storage_enabled === true;
  } catch {
    storageEnabled = false;
  }
}

export function openAgent(name) {
  currentAgent = name;
  activeTab = "overview";
  apiStats = null;
  apiEvents = null;
  _updateTabUI();
  _renderActiveTab();
  panel.hidden = false;

  // Fetch API data in background
  if (storageEnabled) {
    _fetchApiData(name);
  }
}

export function close() {
  panel.hidden = true;
  currentAgent = null;
}

export function refresh() {
  if (!panel.hidden && currentAgent) _renderActiveTab();
}

async function _fetchApiData(agentName) {
  try {
    const [statsResp, eventsResp] = await Promise.all([
      fetch(`/api/agents/${encodeURIComponent(agentName)}/stats`),
      fetch(`/api/agents/${encodeURIComponent(agentName)}/events?limit=200`),
    ]);
    if (statsResp.ok) apiStats = await statsResp.json();
    if (eventsResp.ok) apiEvents = await eventsResp.json();
    if (currentAgent === agentName) _renderActiveTab();
  } catch {
    // Storage not available — use in-memory only
  }
}

function _switchTab(tab) {
  activeTab = tab;
  _updateTabUI();
  _renderActiveTab();
}

function _updateTabUI() {
  panel.querySelectorAll(".agent-detail__tab").forEach(btn => {
    btn.classList.toggle("agent-detail__tab--active", btn.dataset.tab === activeTab);
  });
  panel.querySelectorAll(".agent-detail__panel").forEach(p => {
    p.classList.toggle("agent-detail__panel--active", p.dataset.panel === activeTab);
  });
}

function _renderActiveTab() {
  if (!currentAgent) return;
  _renderHeader();
  switch (activeTab) {
    case "overview": _renderOverview(); break;
    case "messages": _renderMessages(); break;
    case "reasoning": _renderReasoning(); break;
    case "performance": _renderPerformance(); break;
  }
}

// ---- Header ----

function _renderHeader() {
  const agent = getAgent(currentAgent);
  const role = AGENT_ROLES[currentAgent] || "";
  const teamId = _findTeam(currentAgent);
  const teamInfo = TEAMS[teamId];

  const nameEl = document.getElementById("agent-detail-name");
  const teamEl = document.getElementById("agent-detail-team");
  const roleEl = document.getElementById("agent-detail-role");
  const statusEl = document.getElementById("agent-detail-status");
  const taskEl = document.getElementById("agent-detail-task");
  const avatarEl = document.getElementById("agent-detail-avatar");

  if (nameEl) nameEl.textContent = currentAgent.replace(/-/g, " ").replace(/_/g, " ");
  if (teamEl) {
    teamEl.textContent = teamInfo?.label || teamId;
    teamEl.style.color = teamInfo?.color || "#64748b";
  }
  if (roleEl) roleEl.textContent = role;
  if (statusEl) {
    const status = agent?.status || "idle";
    statusEl.textContent = status;
    statusEl.className = `agent-detail__value agent-detail__status--${status}`;
  }
  if (taskEl) {
    taskEl.textContent = agent?.task || "";
    taskEl.hidden = !agent?.task;
  }
  if (avatarEl) {
    avatarEl.style.backgroundColor = teamInfo?.color || "#64748b";
    avatarEl.textContent = (currentAgent[0] || "?").toUpperCase();
  }
}

// ---- Overview Tab ----

function _renderOverview() {
  const allComms = getComms();
  const events = getEventsForAgent(currentAgent);
  const cost = getCostForAgent(currentAgent);

  // Stats — use API data if available, fallback to in-memory
  const tasks = apiStats?.task_count ?? events.filter(e => e.type === "active").length;
  const errors = apiStats?.error_count ?? events.filter(e => e.type === "error").length;
  const messages = apiStats?.messages_sent ?? allComms.filter(
    c => c.agent === currentAgent && c.type === "message"
  ).length;

  _setText("stat-tasks", tasks);
  _setText("stat-cost", `$${(apiStats?.total_cost ?? cost).toFixed(4)}`);
  _setText("stat-messages", messages);
  _setText("stat-errors", errors);

  // Recent activity
  const eventsEl = document.getElementById("agent-detail-events");
  if (eventsEl) {
    const recent = events.slice(-15);
    eventsEl.innerHTML = recent.length
      ? recent.map(e => `<div class="agent-detail__event">
          <span class="agent-detail__event-time">${_fmtTime(e.time)}</span>
          <span class="agent-detail__event-text">${_esc(e.text)}</span>
        </div>`).join("")
      : "<div class='agent-detail__empty'>No recent activity</div>";
    eventsEl.scrollTop = eventsEl.scrollHeight;
  }

  // Communication partners
  const partnersEl = document.getElementById("agent-detail-partners");
  if (partnersEl) {
    const partners = apiStats?.communication_partners || _computePartners(allComms);
    const entries = Object.entries(partners).sort((a, b) => b[1] - a[1]);
    partnersEl.innerHTML = entries.length
      ? entries.map(([name, count]) => {
          const teamId = _findTeam(name);
          const color = TEAMS[teamId]?.color || "#64748b";
          return `<div class="agent-detail__partner" data-agent="${_esc(name)}">
            <span class="agent-detail__partner-dot" style="background:${color}"></span>
            <span class="agent-detail__partner-name">${_esc(name.replace(/-/g, " "))}</span>
            <span class="agent-detail__partner-count">${count} msg</span>
          </div>`;
        }).join("")
      : "<div class='agent-detail__empty'>No communication partners</div>";

    // Click partner to open their detail
    partnersEl.querySelectorAll("[data-agent]").forEach(el => {
      el.addEventListener("click", () => openAgent(el.dataset.agent));
    });
  }
}

function _computePartners(allComms) {
  const partners = {};
  for (const c of allComms) {
    if (c.type === "message") {
      if (c.agent === currentAgent && c.content?.includes("→")) {
        const to = c.content.split("→")[1]?.trim().split(":")[0]?.trim();
        if (to) partners[to] = (partners[to] || 0) + 1;
      }
    }
  }
  return partners;
}

// ---- Messages Tab ----

function _renderMessages() {
  const el = document.getElementById("agent-detail-messages");
  if (!el) return;

  const dirFilter = document.getElementById("msg-direction-filter")?.value || "";
  const searchTerm = (document.getElementById("msg-search")?.value || "").toLowerCase();

  // Gather messages from in-memory comms + API events
  let messages = _gatherMessages();

  if (dirFilter === "sent") messages = messages.filter(m => m.direction === "sent");
  if (dirFilter === "received") messages = messages.filter(m => m.direction === "received");
  if (searchTerm) messages = messages.filter(m =>
    m.content.toLowerCase().includes(searchTerm) ||
    m.counterpart.toLowerCase().includes(searchTerm)
  );

  el.innerHTML = messages.length
    ? messages.map(m => `<div class="msg-entry msg-entry--${m.direction}">
        <div class="msg-entry__header">
          <span class="msg-entry__dir">${m.direction === "sent" ? "→" : "←"}</span>
          <span class="msg-entry__agent" data-agent="${_esc(m.counterpart)}">${_esc(m.counterpart)}</span>
          <span class="msg-entry__tag">${_esc(m.tag)}</span>
          <span class="msg-entry__time">${_fmtTime(m.time)}</span>
        </div>
        <div class="msg-entry__content">${_esc(m.content)}</div>
      </div>`).join("")
    : "<div class='agent-detail__empty'>No messages found</div>";

  // Click counterpart to navigate
  el.querySelectorAll("[data-agent]").forEach(a => {
    a.addEventListener("click", () => openAgent(a.dataset.agent));
  });
}

function _gatherMessages() {
  const comms = getComms();
  const messages = [];

  for (const c of comms) {
    if (c.type !== "message") continue;
    // Parse "agentA → agentB: content"
    const match = c.content?.match(/^(.+?)\s*→\s*(.+?):\s*(.*)$/s);
    if (!match) continue;
    const [, from, to, content] = match;
    const fromClean = from.trim();
    const toClean = to.trim();

    if (fromClean === currentAgent) {
      messages.push({
        direction: "sent",
        counterpart: toClean,
        content: content.trim(),
        tag: c.tag || "data",
        time: c.time,
      });
    } else if (toClean === currentAgent) {
      messages.push({
        direction: "received",
        counterpart: fromClean,
        content: content.trim(),
        tag: c.tag || "data",
        time: c.time,
      });
    }
  }

  // Also gather from API events if available
  if (apiEvents?.events) {
    for (const evt of apiEvents.events) {
      if (evt.type !== "message_flow") continue;
      const p = evt.payload || {};
      if (p.from === currentAgent) {
        if (!messages.some(m => m.time === evt.timestamp && m.counterpart === p.to)) {
          messages.push({
            direction: "sent",
            counterpart: p.to || "unknown",
            content: p.content || "",
            tag: p.tag || "data",
            time: evt.timestamp,
          });
        }
      } else if (p.to === currentAgent) {
        if (!messages.some(m => m.time === evt.timestamp && m.counterpart === p.from)) {
          messages.push({
            direction: "received",
            counterpart: p.from || "unknown",
            content: p.content || "",
            tag: p.tag || "data",
            time: evt.timestamp,
          });
        }
      }
    }
  }

  return messages.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
}

// ---- Reasoning Tab ----

function _renderReasoning() {
  const el = document.getElementById("agent-detail-reasoning");
  const costEl = document.getElementById("reasoning-total-cost");
  if (!el) return;

  const searchTerm = (document.getElementById("reasoning-search")?.value || "").toLowerCase();
  let entries = _gatherReasoning();

  if (searchTerm) {
    entries = entries.filter(e => e.text.toLowerCase().includes(searchTerm));
  }

  // Total reasoning cost
  const totalCost = entries.reduce((sum, e) => sum + (e.cost || 0), 0);
  if (costEl) costEl.textContent = `Total reasoning cost: $${totalCost.toFixed(4)}`;

  el.innerHTML = entries.length
    ? entries.map((e, i) => `<div class="reasoning-entry reasoning-entry--${e.entryType}">
        <div class="reasoning-entry__header">
          <span class="reasoning-entry__icon">${_reasoningIcon(e.entryType)}</span>
          <span class="reasoning-entry__type">${e.entryType}</span>
          ${e.model ? `<span class="reasoning-entry__model">${_esc(e.model)}</span>` : ""}
          ${e.tokens ? `<span class="reasoning-entry__tokens">${e.tokens} tok</span>` : ""}
          <span class="reasoning-entry__time">${_fmtTime(e.time)}</span>
        </div>
        <div class="reasoning-entry__body ${e.text.length > 200 ? "reasoning-entry__body--collapsed" : ""}"
             id="reasoning-body-${i}">
          ${_esc(e.text)}
        </div>
        ${e.text.length > 200 ? `<button class="reasoning-entry__expand" onclick="
          const body = document.getElementById('reasoning-body-${i}');
          body.classList.toggle('reasoning-entry__body--collapsed');
          this.textContent = body.classList.contains('reasoning-entry__body--collapsed') ? 'Expand ▼' : 'Collapse ▲';
        ">Expand ▼</button>` : ""}
      </div>`).join("")
    : "<div class='agent-detail__empty'>No reasoning data yet</div>";
}

function _gatherReasoning() {
  const entries = [];

  // From in-memory comms
  for (const c of getComms()) {
    if (c.agent !== currentAgent) continue;
    if (c.type === "thinking") {
      entries.push({
        entryType: "thinking",
        text: c.content || "",
        time: c.time,
        model: "",
        tokens: 0,
        cost: 0,
      });
    } else if (c.type === "done") {
      entries.push({
        entryType: "output",
        text: c.content || "",
        time: c.time,
        model: "",
        tokens: 0,
        cost: 0,
      });
    } else if (c.type === "error") {
      entries.push({
        entryType: "error",
        text: c.content || "",
        time: c.time,
        model: "",
        tokens: 0,
        cost: 0,
      });
    }
  }

  // From API events — richer data with model/token info
  if (apiEvents?.events) {
    for (const evt of apiEvents.events) {
      if (evt.agent_id !== currentAgent) continue;
      const p = evt.payload || {};

      if (evt.type === "agent_status" && p.status === "active" && p.thinking) {
        if (!entries.some(e => e.time === evt.timestamp && e.text === p.thinking)) {
          entries.push({
            entryType: "thinking",
            text: p.thinking,
            time: evt.timestamp,
            model: p.model || "",
            tokens: (p.tokens_in || 0) + (p.tokens_out || 0),
            cost: p.cost || 0,
          });
        }
      } else if (evt.type === "cost_update") {
        entries.push({
          entryType: "cost",
          text: `Cost: $${(p.cost || 0).toFixed(4)} | ${p.tokens_in || 0} in / ${p.tokens_out || 0} out`,
          time: evt.timestamp,
          model: p.model || "",
          tokens: (p.tokens_in || 0) + (p.tokens_out || 0),
          cost: p.cost || 0,
        });
      } else if (evt.type === "error") {
        if (!entries.some(e => e.time === evt.timestamp && e.entryType === "error")) {
          entries.push({
            entryType: "error",
            text: p.error || "Unknown error",
            time: evt.timestamp,
            model: "",
            tokens: 0,
            cost: 0,
          });
        }
      }
    }
  }

  return entries.sort((a, b) => (a.time || "").localeCompare(b.time || ""));
}

function _reasoningIcon(type) {
  switch (type) {
    case "thinking": return "🧠";
    case "output": return "📤";
    case "error": return "❌";
    case "cost": return "💰";
    case "tool_call": return "🔧";
    default: return "•";
  }
}

// ---- Performance Tab ----

function _renderPerformance() {
  _renderCostBreakdown();
  _renderTokenUsage();
  _renderTaskTimeline();
}

function _renderCostBreakdown() {
  const el = document.getElementById("agent-perf-cost");
  if (!el) return;

  const costData = [];
  if (apiEvents?.events) {
    for (const evt of apiEvents.events) {
      if (evt.type === "cost_update" && evt.agent_id === currentAgent) {
        costData.push({
          cost: evt.payload?.cost || 0,
          model: evt.payload?.model || "unknown",
          time: evt.timestamp,
        });
      }
    }
  }

  if (!costData.length) {
    const cost = getCostForAgent(currentAgent);
    el.innerHTML = `<div class="perf-stat">Total: <strong>$${cost.toFixed(4)}</strong></div>`;
    return;
  }

  // Group by model
  const byModel = {};
  let cumulative = 0;
  for (const d of costData) {
    byModel[d.model] = (byModel[d.model] || 0) + d.cost;
    cumulative += d.cost;
  }

  const modelEntries = Object.entries(byModel).sort((a, b) => b[1] - a[1]);
  const maxCost = Math.max(...modelEntries.map(e => e[1]), 0.001);

  el.innerHTML = `
    <div class="perf-stat">Total: <strong>$${cumulative.toFixed(4)}</strong> across ${costData.length} calls</div>
    ${modelEntries.map(([model, cost]) => `
      <div class="perf-bar">
        <span class="perf-bar__label">${_esc(model)}</span>
        <div class="perf-bar__track">
          <div class="perf-bar__fill" style="width:${(cost / maxCost * 100).toFixed(1)}%"></div>
        </div>
        <span class="perf-bar__value">$${cost.toFixed(4)}</span>
      </div>
    `).join("")}
  `;
}

function _renderTokenUsage() {
  const el = document.getElementById("agent-perf-tokens");
  if (!el) return;

  let totalIn = 0, totalOut = 0;
  if (apiEvents?.events) {
    for (const evt of apiEvents.events) {
      if (evt.type === "cost_update" && evt.agent_id === currentAgent) {
        totalIn += evt.payload?.tokens_in || 0;
        totalOut += evt.payload?.tokens_out || 0;
      }
    }
  } else if (apiStats) {
    totalIn = apiStats.total_tokens_in || 0;
    totalOut = apiStats.total_tokens_out || 0;
  }

  const total = totalIn + totalOut;
  const inPct = total > 0 ? (totalIn / total * 100).toFixed(1) : 50;
  const outPct = total > 0 ? (totalOut / total * 100).toFixed(1) : 50;

  el.innerHTML = `
    <div class="token-bar">
      <div class="token-bar__segment token-bar__segment--in" style="width:${inPct}%">
        ${totalIn.toLocaleString()} in
      </div>
      <div class="token-bar__segment token-bar__segment--out" style="width:${outPct}%">
        ${totalOut.toLocaleString()} out
      </div>
    </div>
    <div class="perf-stat">Total: <strong>${total.toLocaleString()}</strong> tokens</div>
  `;
}

function _renderTaskTimeline() {
  const el = document.getElementById("agent-perf-timeline");
  if (!el) return;

  // Build task durations from status events
  const tasks = [];
  let taskStart = null;

  const events = apiEvents?.events || [];
  for (const evt of events) {
    if (evt.agent_id !== currentAgent) continue;
    if (evt.type === "agent_status") {
      const status = evt.payload?.status;
      if (status === "active" && !taskStart) {
        taskStart = { start: evt.timestamp, thinking: evt.payload?.thinking || "" };
      } else if (status === "idle" && taskStart) {
        tasks.push({ ...taskStart, end: evt.timestamp });
        taskStart = null;
      }
    }
  }

  if (!tasks.length) {
    el.innerHTML = "<div class='agent-detail__empty'>No task timeline data</div>";
    return;
  }

  el.innerHTML = tasks.map((t, i) => {
    const start = new Date(t.start);
    const end = new Date(t.end);
    const durationMs = end - start;
    const duration = durationMs > 60000
      ? `${(durationMs / 60000).toFixed(1)}m`
      : `${(durationMs / 1000).toFixed(1)}s`;

    return `<div class="timeline-entry">
      <span class="timeline-entry__index">#${i + 1}</span>
      <span class="timeline-entry__duration">${duration}</span>
      <span class="timeline-entry__desc">${_esc(t.thinking).substring(0, 60)}</span>
    </div>`;
  }).join("");
}

// ---- Helpers ----

function _findTeam(agentName) {
  for (const [teamId, team] of Object.entries(TEAMS)) {
    if (team.agents?.includes(agentName)) return teamId;
  }
  return "unknown";
}

function _setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function _fmtTime(t) {
  if (!t) return "";
  try {
    const d = new Date(t);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

function _esc(s) {
  if (!s) return "";
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
