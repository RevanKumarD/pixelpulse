/**
 * Centralized State Store
 *
 * Reactive state management for the dashboard. Components subscribe
 * to state changes and re-render only when relevant state mutates.
 *
 * TEAMS, AGENT_ROLES, PIPELINE_STAGES, and STAGE_TO_TEAM are loaded
 * dynamically from /api/config on startup via loadConfig().
 */

// --- Agent & Team Registry (populated dynamically from /api/config) ---

export let TEAMS = {};
export let AGENT_ROLES = {};
export let PIPELINE_STAGES = [];
export let STAGE_TO_TEAM = {};

// --- State ---

const state = {
  agents: {},
  orchestrator: {
    status: "idle",       // idle | active | waiting
    currentStage: "",
    message: "",
    runName: "",
  },
  pipeline: { stage: "", runs: [] },
  totalCost: 0,
  events: [],
  comms: [],
  bubbles: [],           // { id, agent, text, type, createdAt, duration }
  particles: [],         // { id, fromAgent, toAgent, progress, color, content }
  connection: "disconnected",

  // Dynamic canvas state
  focusedRoom: null,          // teamId of focused room, or null
  collapsedRooms: new Set(),  // Set of collapsed teamId strings
  hiddenTeams: new Set(),     // Set of hidden teamId strings (team filter)
};

/**
 * Load dashboard configuration from /api/config.
 *
 * The config response must include:
 *   - teams: { teamId: { label, role, icon, color, agents: [...] } }
 *   - agent_roles: { agentId: "description" }
 *   - pipeline_stages: ["stage1", "stage2", ...]
 *   - stage_to_team: { stageName: teamId | null }
 *
 * This MUST be called before initializing the renderer or any other module.
 */
export async function loadConfig() {
  try {
    const resp = await fetch("/api/config");
    if (!resp.ok) {
      throw new Error(`Config fetch failed: ${resp.status} ${resp.statusText}`);
    }
    const config = await resp.json();

    // Populate the exported registries
    TEAMS = config.teams || {};
    AGENT_ROLES = config.agent_roles || {};
    PIPELINE_STAGES = config.pipeline_stages || [];
    STAGE_TO_TEAM = config.stage_to_team || {};

    // Initialize agent state from team registry
    state.agents = {};
    for (const [teamId, team] of Object.entries(TEAMS)) {
      for (const name of team.agents) {
        state.agents[name] = {
          name,
          team: teamId,
          status: "idle",
          task: "",
          cost: 0,
        };
      }
    }
    // Add orchestrator if not already an agent
    if (!state.agents["orchestrator"]) {
      state.agents["orchestrator"] = {
        name: "orchestrator",
        team: "orchestrator",
        status: "idle",
        task: "",
        cost: 0,
      };
    }

    console.log(
      `[State] Config loaded: ${Object.keys(TEAMS).length} teams, ` +
      `${Object.keys(state.agents).length} agents, ` +
      `${PIPELINE_STAGES.length} pipeline stages`
    );

    // Restore persisted collapsed rooms
    try {
      const saved = localStorage.getItem('pixelpulse-collapsed');
      if (saved) {
        const ids = JSON.parse(saved);
        for (const id of ids) state.collapsedRooms.add(id);
      }
    } catch { /* ignore corrupt data */ }
  } catch (err) {
    console.error("[State] Failed to load config from /api/config:", err);
    // Leave registries empty — dashboard will show a blank state
    // The demo mode and renderer will handle missing data gracefully
  }
}

// --- Subscriptions ---

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify(changeType, detail) {
  for (const fn of listeners) {
    try {
      fn(changeType, detail);
    } catch (err) {
      console.error("State listener error:", err);
    }
  }
}

// --- State Accessors ---

export function getAgent(name) {
  return state.agents[name] || null;
}

export function getAllAgents() {
  return { ...state.agents };
}

export function getTeamAgents(teamId) {
  const team = TEAMS[teamId];
  if (!team) return [];
  return team.agents.map((n) => state.agents[n]).filter(Boolean);
}

export function getPipeline() {
  return { ...state.pipeline };
}

export function getTotalCost() {
  return state.totalCost;
}

export function getEvents() {
  return [...state.events];
}

export function getComms() {
  return [...state.comms];
}

export function getBubbles() {
  return [...state.bubbles];
}

export function getParticles() {
  return [...state.particles];
}

export function getOrchestrator() {
  return { ...state.orchestrator };
}

export function getConnection() {
  return state.connection;
}

// --- State Mutators (immutable updates) ---

export function updateAgent(name, updates) {
  if (!state.agents[name]) return;
  state.agents[name] = { ...state.agents[name], ...updates };
  notify("agent", { name, ...state.agents[name] });
}

export function updateOrchestrator(updates) {
  state.orchestrator = { ...state.orchestrator, ...updates };
  notify("orchestrator", state.orchestrator);
}

export function updatePipeline(updates) {
  state.pipeline = { ...state.pipeline, ...updates };
  notify("pipeline", state.pipeline);
}

export function updateCost(agentId, cost, total) {
  if (agentId && state.agents[agentId]) {
    state.agents[agentId] = { ...state.agents[agentId], cost };
  }
  if (total !== undefined) {
    state.totalCost = total;
  }
  notify("cost", { agentId, cost, total: state.totalCost });
}

// --- Speech Bubbles (timed, with auto-expire) ---

let bubbleIdCounter = 0;

export function addBubble(agent, text, type = "thinking", duration = 6000) {
  const id = ++bubbleIdCounter;
  const bubble = { id, agent, text, type, createdAt: Date.now(), duration };
  // Replace existing bubble for same agent (only one bubble per agent)
  state.bubbles = [
    bubble,
    ...state.bubbles.filter(b => b.agent !== agent),
  ].slice(0, 20);
  notify("bubble", bubble);
  return id;
}

export function expireBubbles() {
  const now = Date.now();
  const before = state.bubbles.length;
  state.bubbles = state.bubbles.filter(b => now - b.createdAt < b.duration);
  if (state.bubbles.length !== before) {
    notify("bubble", null);
  }
}

// --- Communication Particles ---

let particleIdCounter = 0;

export function addParticle(fromAgent, toAgent, color, content, tag) {
  const id = ++particleIdCounter;
  const particle = { id, fromAgent, toAgent, progress: 0, color, content, tag: tag || "" };
  state.particles = [...state.particles, particle].slice(-15);
  notify("particle", particle);
  return id;
}

export function tickParticles(dt = 0.015) {
  state.particles = state.particles
    .map(p => ({ ...p, progress: p.progress + dt }))
    .filter(p => p.progress < 1.0);
}

// --- Comms Feed ---

export function addComm(comm) {
  const ts = comm.timestamp
    ? new Date(comm.timestamp).toLocaleTimeString()
    : new Date().toLocaleTimeString();
  const entry = { time: ts, ...comm };
  state.comms = [entry, ...state.comms.slice(0, 99)];
  notify("comm", entry);
}

// --- Events ---

// Human-readable event descriptions
function _formatEventText(type, p) {
  const agentLabel = (id) => id ? id.replace(/-/g, " ") : "unknown";
  const stageLabel = (s) => s ? s.replace(/_/g, " ") : "";

  switch (type) {
    case "agent_status": {
      const name = agentLabel(p.agent_id);
      const status = p.status || "idle";
      if (status === "active" && p.thinking) {
        return `agent_status ${p.agent_id} \u2014 ${p.thinking.slice(0, 60)}`;
      }
      if (status === "active") return `agent_status ${p.agent_id} \u2014 started working`;
      if (status === "idle") return `agent_status ${p.agent_id} \u2014 task complete, now idle`;
      if (status === "error") return `agent_status ${p.agent_id} \u2014 error encountered`;
      if (status === "waiting") return `agent_status ${p.agent_id} \u2014 waiting for input`;
      return `agent_status ${p.agent_id} \u2014 ${status}`;
    }
    case "message_flow": {
      const tag = p.tag || "data";
      const content = p.content ? ` \u2014 ${p.content.slice(0, 50)}` : "";
      return `message_flow ${p.from}\u2192${p.to} [${tag}]${content}`;
    }
    case "pipeline_progress": {
      const stage = stageLabel(p.stage);
      return `pipeline_progress \u2192 ${p.stage}`;
    }
    case "cost_update": {
      const cost = p.cost != null ? `$${p.cost.toFixed(4)}` : "";
      return `cost_update ${p.agent_id || ""} ${cost}`;
    }
    case "error": {
      return `error ${p.agent_id || ""} \u2014 ${(p.message || p.error || "unknown error").slice(0, 60)}`;
    }
    case "state_snapshot": return "state_snapshot";
    default: {
      let text = type;
      if (p.agent_id) text += ` ${p.agent_id}`;
      if (p.stage) text += ` \u2192 ${p.stage}`;
      if (p.from) text += ` ${p.from}\u2192${p.to}`;
      return text;
    }
  }
}

export function addEvent(event) {
  const ts = event.timestamp
    ? new Date(event.timestamp).toLocaleTimeString()
    : new Date().toLocaleTimeString();
  const p = event.payload || {};
  const text = _formatEventText(event.type, p);
  state.events = [{ time: ts, text, type: event.type }, ...state.events.slice(0, 49)];
  notify("event", state.events[0]);

  // Route rich events into comms, bubbles, and particles
  if (event.type === "agent_status") {
    if (p.thinking) {
      addComm({
        timestamp: event.timestamp,
        type: "thinking",
        agent: p.agent_id,
        content: p.thinking,
        decision: p.decision || "",
        status: p.status,
      });
      // Show speech bubble on canvas
      const bubbleType = p.status === "active" ? "thinking" : p.status === "error" ? "error" : "done";
      addBubble(p.agent_id, p.thinking, bubbleType, p.status === "active" ? 6000 : 4000);
    }
  }

  if (event.type === "message_flow") {
    if (p.content) {
      addComm({
        timestamp: event.timestamp,
        type: "message",
        from: p.from,
        to: p.to,
        content: p.content,
        tag: p.tag || "data",
      });
    }
    // Spawn particle — color by data tag for visual distinction
    const TAG_COLORS = {
      signals:   "#00d4ff",  // research blue
      clusters:  "#7c3aed",  // purple
      scores:    "#06b6d4",  // cyan
      brief:     "#3b82f6",  // blue
      prompts:   "#ff6ec7",  // design pink
      artifacts: "#ec4899",  // hot pink
      qa:        "#f59e0b",  // amber
      listings:  "#39ff14",  // commerce green
      localized: "#22d3ee",  // teal
      feedback:  "#ffae00",  // learning gold
      analysis:  "#f97316",  // orange
      memory:    "#a855f7",  // violet
      data:      "#64748b",  // neutral
    };
    const tagColor = TAG_COLORS[p.tag] || TAG_COLORS.data;
    addParticle(p.from, p.to, tagColor, p.content || "", p.tag || "data");
    // Show bubble on receiving agent
    if (p.content) {
      addBubble(p.to, `\u2190 ${p.content.slice(0, 60)}`, "receiving", 5000);
    }
  }

  if (event.type === "pipeline_progress") {
    if (p.message) {
      addComm({
        timestamp: event.timestamp,
        type: "pipeline",
        content: p.message,
        stage: p.stage,
        status: p.status,
      });
    }
    // Update orchestrator
    updateOrchestrator({
      status: p.status === "waiting" ? "waiting" : "active",
      currentStage: p.stage || "",
      message: p.message || "",
    });
  }

  if (event.type === "error") {
    addComm({
      timestamp: event.timestamp,
      type: "error",
      agent: p.agent_id,
      content: p.error || "Unknown error",
    });
    if (p.agent_id) {
      addBubble(p.agent_id, `ERROR: ${(p.error || "").slice(0, 50)}`, "error", 8000);
    }
  }
}

export function setConnection(status) {
  state.connection = status;
  notify("connection", status);
}

export function getEventsForAgent(name) {
  return getEvents().filter(e => e.text.includes(name));
}

export function getCostForAgent(name) {
  const agent = getAgent(name);
  return agent?.cost || 0;
}

// ---- Focus Mode ----

export function getFocusedRoom() { return state.focusedRoom; }

export function setFocusedRoom(teamId) {
  const prev = state.focusedRoom;
  state.focusedRoom = teamId;
  notify("focusChanged", { teamId, prev });
}

// ---- Collapsed Rooms ----

export function isRoomCollapsed(teamId) { return state.collapsedRooms.has(teamId); }

export function toggleRoomCollapsed(teamId) {
  if (state.collapsedRooms.has(teamId)) {
    state.collapsedRooms.delete(teamId);
  } else {
    state.collapsedRooms.add(teamId);
  }
  // Persist to localStorage
  localStorage.setItem('pixelpulse-collapsed', JSON.stringify([...state.collapsedRooms]));
  notify("roomCollapsed", { teamId, collapsed: state.collapsedRooms.has(teamId) });
}

// ---- Hidden Teams (Filter) ----

export function isTeamHidden(teamId) { return state.hiddenTeams.has(teamId); }

export function setHiddenTeams(teamIds) {
  state.hiddenTeams = new Set(teamIds);
  notify("teamsFiltered", { hidden: [...state.hiddenTeams] });
}

export function getVisibleTeamIds() {
  return Object.keys(TEAMS).filter(id => !state.hiddenTeams.has(id));
}
