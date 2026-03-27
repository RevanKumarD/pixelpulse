/**
 * Agent Detail Panel
 *
 * Click-to-inspect overlay showing agent name, team, role, status,
 * recent activity, and cost. Listens for canvas agent-click events
 * and sidebar agent row clicks.
 */
import { getAgent, AGENT_ROLES, TEAMS, getEventsForAgent, getCostForAgent } from "./state.js";

let panel, nameEl, teamEl, roleEl, statusEl, eventsEl, costEl;
let currentAgent = null;

export function init() {
  panel = document.getElementById("agent-detail");
  if (!panel) return;
  nameEl = document.getElementById("agent-detail-name");
  teamEl = document.getElementById("agent-detail-team");
  roleEl = document.getElementById("agent-detail-role");
  statusEl = document.getElementById("agent-detail-status");
  eventsEl = document.getElementById("agent-detail-events");
  costEl = document.getElementById("agent-detail-cost");

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

  // Close on click outside (exclude sidebar agent rows and canvas)
  document.addEventListener("click", (e) => {
    if (!panel.hidden
        && !panel.contains(e.target)
        && !e.target.closest("canvas")
        && !e.target.closest("[data-agent]")) {
      close();
    }
  });
}

export function openAgent(name) {
  currentAgent = name;
  _render();
  panel.hidden = false;
}

export function close() {
  panel.hidden = true;
  currentAgent = null;
}

/** Called by the render loop to refresh the panel if open */
export function refresh() {
  if (!panel.hidden && currentAgent) _render();
}

function _render() {
  if (!currentAgent) return;
  const agent = getAgent(currentAgent);
  const role = AGENT_ROLES[currentAgent] || "";
  const teamName = _findTeam(currentAgent);

  nameEl.textContent = currentAgent.replace(/-/g, " ");
  teamEl.textContent = teamName;
  teamEl.className = `agent-detail__team agent-detail__team--${teamName}`;
  roleEl.textContent = role;
  statusEl.textContent = agent?.status || "idle";
  statusEl.className = `agent-detail__value agent-detail__status--${agent?.status || "idle"}`;

  // Recent events
  const events = getEventsForAgent(currentAgent).slice(-10);
  eventsEl.innerHTML = events.length
    ? events.map(e => `<div class="agent-detail__event">${_escapeHtml(e.text)}</div>`).join("")
    : "<div class='agent-detail__empty'>No recent activity</div>";

  // Cost
  const cost = getCostForAgent(currentAgent);
  costEl.textContent = `$${cost.toFixed(4)}`;
}

function _findTeam(agentName) {
  for (const [teamId, team] of Object.entries(TEAMS)) {
    if (team.agents.includes(agentName)) return teamId;
  }
  return "unknown";
}

function _escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
