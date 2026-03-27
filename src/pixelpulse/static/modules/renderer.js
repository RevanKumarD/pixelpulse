/**
 * Canvas 2D Office Renderer — "Mission Control" overhaul
 *
 * Renders a pixel-art office with:
 * - 4 team rooms with clear department labels & roles
 * - Central orchestrator zone showing pipeline status
 * - Animated character sprites with FULL readable names
 * - Word-wrapped speech bubbles that persist (not truncated)
 * - Communication particles flying between agents
 * - Z-sorted rendering (back-to-front by Y position)
 * - Responsive canvas with generous zoom
 */

import {
  TEAMS,
  AGENT_ROLES,
  PIPELINE_STAGES,
  STAGE_TO_TEAM,
  subscribe,
  getAgent,
  getTeamAgents,
  getPipeline,
  getTotalCost,
  getEvents,
  getComms,
  getAllAgents,
  getBubbles,
  getParticles,
  getOrchestrator,
  expireBubbles,
  tickParticles,
} from "./state.js";
import {
  TILE_SIZE,
  getCachedSprite,
  getCharFrame,
  getWalkFrame,
  areSpritesLoaded,
  DESK_SPRITE,
  MONITOR_SPRITE,
  CHAIR_SPRITE,
  PLANT_SPRITE,
  BOOKSHELF_SPRITE,
  WHITEBOARD_SPRITE,
  EASEL_SPRITE,
  BOX_SPRITE,
  TROPHY_SPRITE,
} from "./sprites.js";
import { get as getSetting, onChange as onSettingChange } from "./settings.js";
import { getCanvasColors } from "./theme.js";

// ---- Animation speed (controlled by settings) ----
let animSpeed = 1.0;

// ---- roundRect polyfill for older browsers ----
if (!CanvasRenderingContext2D.prototype.roundRect) {
  CanvasRenderingContext2D.prototype.roundRect = function (x, y, w, h, r) {
    const rad = typeof r === "number" ? r : 0;
    this.moveTo(x + rad, y);
    this.lineTo(x + w - rad, y);
    this.arcTo(x + w, y, x + w, y + rad, rad);
    this.lineTo(x + w, y + h - rad);
    this.arcTo(x + w, y + h, x + w - rad, y + h, rad);
    this.lineTo(x + rad, y + h);
    this.arcTo(x, y + h, x, y + h - rad, rad);
    this.lineTo(x, y + rad);
    this.arcTo(x, y, x + rad, y, rad);
    this.closePath();
  };
}

// ---- Layout Constants ----
const ROOM_COLS = 9;
const ROOM_ROWS = 9;
const ROOM_GAP = 3;          // tiles gap (center = orchestrator zone)
const ROOMS_PER_ROW = 2;
const SITTING_OFFSET = 12;
const ORCH_ROWS = 3;         // orchestrator zone height in tiles

// Team colors for room walls/floors
const TEAM_STYLES = {
  research: { wall: "#0e4d64", floor1: "#0c1a2a", floor2: "#0f2236", accent: "#00d4ff" },
  design:   { wall: "#4a1942", floor1: "#1a0c20", floor2: "#220f28", accent: "#ff6ec7" },
  commerce: { wall: "#14432d", floor1: "#0c1a10", floor2: "#0f2214", accent: "#39ff14" },
  learning: { wall: "#4a3510", floor1: "#1a1408", floor2: "#22190a", accent: "#ffae00" },
};

// ---- State ----
let canvas, ctx;
let zoom = 2;
let baseZoom = 2;     // auto-calculated to fit content
let userZoom = 1;     // user's manual zoom multiplier
let panX = 0, panY = 0;  // pan offset in pixels
let isPanning = false;
let panStartX = 0, panStartY = 0;
let tick = 0;
let hoveredAgent = null;
let mouseX = 0, mouseY = 0;

// Agent screen positions for particles & tooltips
const agentPositions = {}; // { agentName: { x, y, w, h } }

// ---- Roaming System — idle agents wander the office with personality ----
// States: "seated" → "paused" → "walking" → "activity" → "paused" → ...
//         When work arrives: any → "returning" → "seated"
// Activities: stretching, looking_around, chatting (near another agent), dancing
const roamState = {};

// ---- Collision Physics — AABB obstacle system ----
// Furniture bounding boxes per room, built from buildRoomLayout
const _roomFurniture = {}; // { teamId: [{ col, row, w, h }] }
// Also include monitor positions in obstacles
const AGENT_RADIUS = 0.4;  // agent body half-size in tiles for collision

function _registerFurniture(teamId, items) {
  _roomFurniture[teamId] = items
    .filter(i => i.type === "desk" || i.type === "monitor" || i.type === "bookshelf" ||
                 i.type === "plant" || i.type === "whiteboard" || i.type === "easel" ||
                 i.type === "box" || i.type === "trophy")
    .map(i => {
      // AABB per furniture type — generous padding so agents don't clip edges
      const pad = 0.3;
      let w, h;
      switch (i.type) {
        case "desk":      w = 2.4; h = 1.6; break;
        case "monitor":   w = 1.0; h = 0.8; break;
        case "bookshelf": w = 1.4; h = 1.6; break;
        default:          w = 1.2; h = 1.2; break; // plant, whiteboard, easel, box, trophy
      }
      return { col: i.col - pad, row: i.row - pad, w: w + pad, h: h + pad };
    });
}

// Point-vs-AABB: does a point (agent center) overlap any furniture box?
function _collidesWithFurniture(teamId, col, row) {
  const boxes = _roomFurniture[teamId] || [];
  for (const b of boxes) {
    if (col >= b.col - AGENT_RADIUS && col <= b.col + b.w + AGENT_RADIUS &&
        row >= b.row - AGENT_RADIUS && row <= b.row + b.h + AGENT_RADIUS) return true;
  }
  return false;
}

// Room walls — hard boundary
const WALL_MIN_COL = 1.2;
const WALL_MAX_COL = ROOM_COLS - 1.8;
const WALL_MIN_ROW = 1.2;
const WALL_MAX_ROW = ROOM_ROWS - 1.8;

function _isInsideRoom(col, row) {
  return col >= WALL_MIN_COL && col <= WALL_MAX_COL &&
         row >= WALL_MIN_ROW && row <= WALL_MAX_ROW;
}

// Agent-to-agent collision: check if position overlaps any other roaming agent
const AGENT_BODY_R = 0.55; // separation radius between agent centers
function _collidesWithAgent(selfName, teamId, col, row) {
  for (const [name, rs] of Object.entries(roamState)) {
    if (name === selfName) continue;
    if (rs.roomTeamId !== teamId) continue;  // only check same-room agents
    if (rs.state === "seated") continue;      // seated agents are at desk, skip
    const dx = col - rs.col;
    const dy = row - rs.row;
    if (dx * dx + dy * dy < AGENT_BODY_R * AGENT_BODY_R) return true;
  }
  return false;
}

// Hard collision check: furniture + walls only (agents use soft separation, not hard block)
function _isBlocked(_selfName, teamId, col, row) {
  return _collidesWithFurniture(teamId, col, row) || !_isInsideRoom(col, row);
}

// Per-tick movement with collision response (slide along furniture/walls)
function _moveWithCollision(selfName, teamId, fromCol, fromRow, toCol, toRow) {
  if (!_isBlocked(selfName, teamId, toCol, toRow)) {
    return { col: toCol, row: toRow, blocked: false };
  }
  if (!_isBlocked(selfName, teamId, toCol, fromRow)) {
    return { col: toCol, row: fromRow, blocked: false };
  }
  if (!_isBlocked(selfName, teamId, fromCol, toRow)) {
    return { col: fromCol, row: toRow, blocked: false };
  }
  return { col: fromCol, row: fromRow, blocked: true };
}

// Check if an L-shaped path segment is clear (sample along the line)
function _isPathClear(teamId, fromCol, fromRow, toCol, toRow) {
  const dx = toCol - fromCol;
  const dy = toRow - fromRow;
  const dist = Math.sqrt(dx * dx + dy * dy);
  const steps = Math.max(3, Math.ceil(dist / 0.3)); // sample every 0.3 tiles
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const c = fromCol + dx * t;
    const r = fromRow + dy * t;
    if (_collidesWithFurniture(teamId, c, r) || !_isInsideRoom(c, r)) return false;
  }
  return true;
}

// Idle activities with animation data
const ACTIVITIES = [
  { name: "stretching",    duration: 120, dirSequence: ["up", "down", "up", "down"] },
  { name: "looking_around", duration: 90, dirSequence: ["left", "right", "left", "down"] },
  { name: "chatting",       duration: 160, dirSequence: ["right", "right", "left", "left"] },
  { name: "dancing",        duration: 100, dirSequence: ["left", "right", "down", "left", "right", "down"] },
  { name: "thinking",       duration: 80, dirSequence: ["up", "up", "down"] },
];

function initRoam(agentName, deskCol, deskRow, teamId) {
  if (roamState[agentName]) {
    roamState[agentName].deskCol = deskCol;
    roamState[agentName].deskRow = deskRow;
    roamState[agentName].roomTeamId = teamId;
    return;
  }
  roamState[agentName] = {
    col: deskCol, row: deskRow,
    targetCol: deskCol, targetRow: deskRow,
    deskCol, deskRow,
    speed: 0.010 + Math.random() * 0.008,
    pauseTimer: Math.floor(Math.random() * 300) + 150,
    direction: "down",
    roomTeamId: teamId,
    state: "paused",
    // Activity state
    activity: null,          // current activity name
    activityTimer: 0,        // remaining ticks
    activityDirIdx: 0,       // current direction in sequence
    // Waypoint path (L-shaped movement instead of diagonal)
    waypoints: [],
    waypointIdx: 0,
  };
}

function _pickSafeTarget(teamId) {
  // Try up to 15 random spots; pick one that doesn't collide with furniture
  for (let attempt = 0; attempt < 15; attempt++) {
    const col = WALL_MIN_COL + 0.5 + Math.random() * (WALL_MAX_COL - WALL_MIN_COL - 1);
    const row = WALL_MIN_ROW + 0.5 + Math.random() * (WALL_MAX_ROW - WALL_MIN_ROW - 1);
    if (!_collidesWithFurniture(teamId, col, row)) {
      return { col, row };
    }
  }
  // Fallback: center of room (always safe)
  return { col: ROOM_COLS / 2, row: ROOM_ROWS / 2 };
}

function _buildWaypoints(rs) {
  // L-shaped path with path clearance validation
  // Try both horizontal-first and vertical-first, pick whichever is clear
  const target = _pickSafeTarget(rs.roomTeamId);
  rs.targetCol = target.col;
  rs.targetRow = target.row;

  const mid1 = { col: target.col, row: rs.row };   // horizontal first
  const mid2 = { col: rs.col, row: target.row };    // vertical first

  // Option A: horizontal then vertical
  const pathA_clear =
    _isPathClear(rs.roomTeamId, rs.col, rs.row, mid1.col, mid1.row) &&
    _isPathClear(rs.roomTeamId, mid1.col, mid1.row, target.col, target.row);

  // Option B: vertical then horizontal
  const pathB_clear =
    _isPathClear(rs.roomTeamId, rs.col, rs.row, mid2.col, mid2.row) &&
    _isPathClear(rs.roomTeamId, mid2.col, mid2.row, target.col, target.row);

  if (pathA_clear && pathB_clear) {
    // Both clear — pick randomly
    rs.waypoints = Math.random() < 0.5
      ? [mid1, target] : [mid2, target];
  } else if (pathA_clear) {
    rs.waypoints = [mid1, target];
  } else if (pathB_clear) {
    rs.waypoints = [mid2, target];
  } else {
    // Neither L-path is clear — try a direct path to a closer safe spot
    const closer = _pickSafeTarget(rs.roomTeamId);
    rs.targetCol = closer.col;
    rs.targetRow = closer.row;
    rs.waypoints = [closer];
  }
  rs.waypointIdx = 0;
}

function _pickActivity(rs) {
  // 40% chance of doing an activity at destination, 60% just pause and look around
  if (Math.random() < 0.4) {
    const act = ACTIVITIES[Math.floor(Math.random() * ACTIVITIES.length)];
    rs.activity = act.name;
    rs.activityTimer = act.duration;
    rs.activityDirIdx = 0;
    rs.state = "activity";
  } else {
    rs.pauseTimer = 60 + Math.floor(Math.random() * 200);
    rs.state = "paused";
    rs.direction = "down";
  }
}

function tickRoaming() {
  const allAgents = getAllAgents();
  for (const [name, agent] of Object.entries(allAgents)) {
    const rs = roamState[name];
    if (!rs) continue;

    // Force return when agent gets work
    if (agent.status !== "idle" && rs.state !== "seated" && rs.state !== "returning") {
      rs.state = "returning";
      rs.waypoints = [{ col: rs.deskCol, row: rs.deskRow }];
      rs.waypointIdx = 0;
    }

    const speed = rs.speed * animSpeed;

    switch (rs.state) {
      case "paused": {
        if (agent.status !== "idle") { rs.state = "returning"; break; }
        rs.pauseTimer--;
        if (rs.pauseTimer <= 0) {
          _buildWaypoints(rs);
          rs.state = "walking";
        }
        break;
      }

      case "walking": {
        if (rs.waypointIdx >= rs.waypoints.length) {
          _pickActivity(rs);
          break;
        }
        const wp = rs.waypoints[rs.waypointIdx];
        const dx = wp.col - rs.col;
        const dy = wp.row - rs.row;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 0.12) {
          rs.col = wp.col;
          rs.row = wp.row;
          rs.waypointIdx++;
        } else {
          const step = Math.min(speed, dist);
          let nextCol = rs.col + (dx / dist) * step;
          let nextRow = rs.row + (dy / dist) * step;

          // Soft avoidance: steer away from nearby agents
          for (const [otherName, otherRs] of Object.entries(roamState)) {
            if (otherName === name || otherRs.roomTeamId !== rs.roomTeamId || otherRs.state === "seated") continue;
            const adx = nextCol - otherRs.col;
            const ady = nextRow - otherRs.row;
            const adist = Math.sqrt(adx * adx + ady * ady);
            if (adist < AGENT_BODY_R * 1.8 && adist > 0.01) {
              // Lateral nudge perpendicular to movement direction
              const nudge = 0.03 * (1 - adist / (AGENT_BODY_R * 1.8));
              nextCol += (adx / adist) * nudge;
              nextRow += (ady / adist) * nudge;
            }
          }

          const result = _moveWithCollision(name, rs.roomTeamId, rs.col, rs.row, nextCol, nextRow);
          rs.col = result.col;
          rs.row = result.row;

          if (result.blocked) {
            // Fully blocked — reroute: pick a new destination
            rs._blockedCount = (rs._blockedCount || 0) + 1;
            if (rs._blockedCount > 30) {
              // Stuck too long — teleport to a safe spot and pause
              const safe = _pickSafeTarget(rs.roomTeamId);
              rs.col = safe.col;
              rs.row = safe.row;
              rs.pauseTimer = 60;
              rs.state = "paused";
              rs._blockedCount = 0;
            }
          } else {
            rs._blockedCount = 0;
            // Direction from actual movement
            const movedDx = rs.col - (rs.col - (dx / dist) * step);
            if (Math.abs(dx) > 0.05) rs.direction = dx > 0 ? "right" : "left";
            else if (Math.abs(dy) > 0.05) rs.direction = dy > 0 ? "down" : "up";
          }
        }
        break;
      }

      case "activity": {
        if (agent.status !== "idle") { rs.state = "returning"; break; }
        rs.activityTimer--;
        // Cycle through direction sequence for the activity animation
        const act = ACTIVITIES.find(a => a.name === rs.activity);
        if (act) {
          const dirChangeRate = Math.floor(act.duration / act.dirSequence.length);
          const elapsed = (act.duration - rs.activityTimer);
          const dirIdx = Math.min(Math.floor(elapsed / dirChangeRate), act.dirSequence.length - 1);
          rs.direction = act.dirSequence[dirIdx];
        }
        if (rs.activityTimer <= 0) {
          rs.activity = null;
          rs.pauseTimer = 80 + Math.floor(Math.random() * 180);
          rs.state = "paused";
          rs.direction = "down";
        }
        break;
      }

      case "returning": {
        // Build L-path back to desk if we don't have waypoints
        if (!rs.waypoints.length || rs.waypointIdx >= rs.waypoints.length) {
          // L-path back: horizontal first, then vertical to desk
          const midH = { col: rs.deskCol, row: rs.row };
          const midV = { col: rs.col, row: rs.deskRow };
          const desk = { col: rs.deskCol, row: rs.deskRow };
          // Try horizontal-first path
          if (_isPathClear(rs.roomTeamId, rs.col, rs.row, midH.col, midH.row) &&
              _isPathClear(rs.roomTeamId, midH.col, midH.row, desk.col, desk.row)) {
            rs.waypoints = [midH, desk];
          } else if (_isPathClear(rs.roomTeamId, rs.col, rs.row, midV.col, midV.row) &&
                     _isPathClear(rs.roomTeamId, midV.col, midV.row, desk.col, desk.row)) {
            rs.waypoints = [midV, desk];
          } else {
            // Direct — collision system will slide around obstacles
            rs.waypoints = [desk];
          }
          rs.waypointIdx = 0;
        }

        const wp = rs.waypoints[rs.waypointIdx];
        const dx = wp.col - rs.col;
        const dy = wp.row - rs.row;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 0.15) {
          rs.col = wp.col;
          rs.row = wp.row;
          rs.waypointIdx++;
          if (rs.waypointIdx >= rs.waypoints.length) {
            rs.col = rs.deskCol;
            rs.row = rs.deskRow;
            rs.state = "seated";
            rs.direction = "down";
            rs.waypoints = [];
            rs._blockedCount = 0;
          }
        } else {
          const dashSpeed = speed * 2.5;
          const step = Math.min(dashSpeed, dist);
          let nextCol = rs.col + (dx / dist) * step;
          let nextRow = rs.row + (dy / dist) * step;

          // Soft avoidance while dashing back
          for (const [otherName, otherRs] of Object.entries(roamState)) {
            if (otherName === name || otherRs.roomTeamId !== rs.roomTeamId || otherRs.state === "seated") continue;
            const adx = nextCol - otherRs.col;
            const ady = nextRow - otherRs.row;
            const adist = Math.sqrt(adx * adx + ady * ady);
            if (adist < AGENT_BODY_R * 1.5 && adist > 0.01) {
              const nudge = 0.04 * (1 - adist / (AGENT_BODY_R * 1.5));
              nextCol += (adx / adist) * nudge;
              nextRow += (ady / adist) * nudge;
            }
          }

          const result = _moveWithCollision(name, rs.roomTeamId, rs.col, rs.row, nextCol, nextRow);
          rs.col = result.col;
          rs.row = result.row;

          if (result.blocked) {
            rs._blockedCount = (rs._blockedCount || 0) + 1;
            if (rs._blockedCount > 20) {
              // Emergency: snap to desk (can't find a path)
              rs.col = rs.deskCol;
              rs.row = rs.deskRow;
              rs.state = "seated";
              rs.direction = "down";
              rs.waypoints = [];
              rs._blockedCount = 0;
            }
          } else {
            rs._blockedCount = 0;
          }

          if (Math.abs(dx) > Math.abs(dy)) rs.direction = dx > 0 ? "right" : "left";
          else rs.direction = dy > 0 ? "down" : "up";
        }
        break;
      }

      case "seated": {
        if (agent.status === "idle") {
          rs.pauseTimer = 200 + Math.floor(Math.random() * 400);
          rs.state = "paused";
        }
        break;
      }
    }
  }

  // ---- Separation pass: push overlapping agents apart ----
  const roamEntries = Object.entries(roamState);
  for (let i = 0; i < roamEntries.length; i++) {
    const [nameA, rsA] = roamEntries[i];
    if (rsA.state === "seated") continue;
    for (let j = i + 1; j < roamEntries.length; j++) {
      const [nameB, rsB] = roamEntries[j];
      if (rsB.state === "seated") continue;
      if (rsA.roomTeamId !== rsB.roomTeamId) continue;

      const dx = rsA.col - rsB.col;
      const dy = rsA.row - rsB.row;
      const distSq = dx * dx + dy * dy;
      const minDist = AGENT_BODY_R;

      if (distSq < minDist * minDist && distSq > 0.001) {
        const dist = Math.sqrt(distSq);
        const overlap = minDist - dist;
        // Strong spring push — 60% of overlap per tick so agents visibly repel
        const strength = Math.max(overlap * 0.6, 0.04);
        const pushX = (dx / dist) * strength;
        const pushY = (dy / dist) * strength;

        // Push both agents apart equally, respecting walls & furniture
        const aCol = Math.max(WALL_MIN_COL, Math.min(rsA.col + pushX, WALL_MAX_COL));
        const aRow = Math.max(WALL_MIN_ROW, Math.min(rsA.row + pushY, WALL_MAX_ROW));
        const bCol = Math.max(WALL_MIN_COL, Math.min(rsB.col - pushX, WALL_MAX_COL));
        const bRow = Math.max(WALL_MIN_ROW, Math.min(rsB.row - pushY, WALL_MAX_ROW));

        if (!_collidesWithFurniture(rsA.roomTeamId, aCol, aRow)) {
          rsA.col = aCol; rsA.row = aRow;
        }
        if (!_collidesWithFurniture(rsB.roomTeamId, bCol, bRow)) {
          rsB.col = bCol; rsB.row = bRow;
        }
      } else if (distSq <= 0.001) {
        // Agents perfectly overlapping — nudge randomly to break deadlock
        const angle = Math.random() * Math.PI * 2;
        const nudge = 0.15;
        const aCol = rsA.col + Math.cos(angle) * nudge;
        const aRow = rsA.row + Math.sin(angle) * nudge;
        if (!_collidesWithFurniture(rsA.roomTeamId, aCol, aRow) && _isInsideRoom(aCol, aRow)) {
          rsA.col = aCol; rsA.row = aRow;
        }
      }
    }
  }
}

// ---- Sidebar DOM refs ----
let pipelineContainer, runsContainer, costContainer, eventLogContainer, commsFeedContainer, agentActivityContainer, connDot, connText;

// ---- Init ----

let initialized = false;

export function init() {
  if (initialized) return;
  initialized = true;
  canvas = document.getElementById("office-canvas");
  ctx = canvas.getContext("2d");

  pipelineContainer = document.getElementById("pipeline-stages");
  runsContainer = document.getElementById("active-runs");
  costContainer = document.getElementById("total-cost");
  eventLogContainer = document.getElementById("event-log");
  commsFeedContainer = document.getElementById("comms-feed");
  agentActivityContainer = document.getElementById("agent-activity");
  connDot = document.querySelector("#conn-status .dot");
  connText = document.querySelector("#conn-status .label");

  resize();
  window.addEventListener("resize", resize);
  canvas.addEventListener("mousemove", onMouseMove);
  canvas.addEventListener("click", onMouseMove);
  canvas.addEventListener("touchstart", (e) => {
    const t = e.touches[0];
    mouseX = t.clientX;
    mouseY = t.clientY;
    detectHover();
  });

  // Wheel zoom — scroll to zoom in/out
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.08 : 0.08;
    userZoom = Math.max(0.5, Math.min(userZoom + delta, 3));
    zoom = baseZoom * userZoom;
  }, { passive: false });

  // Pan — middle-click or shift+click drag
  canvas.addEventListener("mousedown", (e) => {
    if (e.button === 1 || (e.button === 0 && e.shiftKey)) {
      isPanning = true;
      panStartX = e.clientX - panX;
      panStartY = e.clientY - panY;
      e.preventDefault();
    }
  });
  window.addEventListener("mousemove", (e) => {
    if (isPanning) {
      panX = e.clientX - panStartX;
      panY = e.clientY - panStartY;
    }
  });
  window.addEventListener("mouseup", () => { isPanning = false; });

  // Double-click to fit view
  canvas.addEventListener("dblclick", () => { fitView(); });

  // Agent-click detection — dispatch custom event when clicking on an agent
  canvas.addEventListener("click", (e) => {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const cx = (e.clientX - rect.left) * dpr;
    const cy = (e.clientY - rect.top) * dpr;
    for (const [name, pos] of Object.entries(agentPositions)) {
      if (cx >= pos.x && cx <= pos.x + pos.w && cy >= pos.y && cy <= pos.y + pos.h) {
        canvas.dispatchEvent(new CustomEvent("agent-click", { detail: { agentName: name } }));
        return;
      }
    }
  });

  // Animation speed from settings
  animSpeed = getSetting("animationSpeed") ?? 1.0;
  onSettingChange("animationSpeed", (v) => { animSpeed = v; });

  // Log filter inputs trigger re-render on change
  for (const id of ["events-search", "events-team-filter"]) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", () => renderEvents());
  }
  for (const id of ["comms-search", "comms-team-filter"]) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", () => renderComms());
  }

  renderPipeline();
  renderCost();
  renderAgentActivity();

  subscribe((type, detail) => {
    switch (type) {
      case "agent": renderAgentActivity(); break;
      case "pipeline": renderPipeline(); renderAgentActivity(); break;
      case "cost": renderCost(); break;
      case "event": renderEvents(); break;
      case "comm": renderComms(); break;
      case "connection": renderConnection(detail); break;
    }
  });

  requestAnimationFrame(gameLoop);
}

// Content bounds in tiles — room grid PLUS everything that extends beyond it:
//   Top:    room label text + subtitle (~2 tiles above top room wall)
//   Bottom: agent chairs/sprites extending below room floor (~2 tiles) + orch message
//   Right:  agent name cards to the right of sprites (~5 tiles)
//   Left:   small margin (~1 tile)
const PAD_TOP = 3;      // room labels above top rooms
const PAD_BOTTOM = 4;   // agents/chairs below bottom rooms + orchestrator text
const PAD_LEFT = 1;
const PAD_RIGHT = 5;    // agent name cards to the right

// The full content area in tiles
const CONTENT_TILES_W = PAD_LEFT + ROOMS_PER_ROW * ROOM_COLS + ROOM_GAP + PAD_RIGHT;
const CONTENT_TILES_H = PAD_TOP + 2 * ROOM_ROWS + ROOM_GAP + PAD_BOTTOM;

function resize() {
  const wrap = document.querySelector(".canvas-wrap");
  const dpr = window.devicePixelRatio || 1;
  const w = wrap.clientWidth;
  const h = wrap.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";

  // Zoom so the full content area (including padding) fits the canvas exactly
  const zoomW = (w * dpr) / (CONTENT_TILES_W * TILE_SIZE);
  const zoomH = (h * dpr) / (CONTENT_TILES_H * TILE_SIZE);
  baseZoom = Math.max(1, Math.min(zoomW, zoomH));
  zoom = baseZoom * userZoom;
}

/** Fit all content in view — recalculates zoom so nothing is clipped */
export function fitView() {
  userZoom = 1;
  panX = 0;
  panY = 0;
  resize();                 // recalculates baseZoom to fit
  zoom = baseZoom * userZoom;
}

/** Zoom in by one step */
export function zoomIn() {
  userZoom = Math.min(userZoom + 0.15, 3);
  zoom = baseZoom * userZoom;
}

/** Zoom out by one step */
export function zoomOut() {
  userZoom = Math.max(userZoom - 0.15, 0.3);
  zoom = baseZoom * userZoom;
}

/** Reset to default view (zoom 1x, no pan) */
export function resetView() {
  userZoom = 1;
  panX = 0;
  panY = 0;
  zoom = baseZoom * userZoom;
}

/** Pan camera to center on a team room */
const TEAM_IDS_ORDER = ["research", "design", "commerce", "learning"];
export function panToTeam(teamId) {
  const idx = TEAM_IDS_ORDER.indexOf(teamId);
  if (idx === -1) return;
  const roomCol = idx % ROOMS_PER_ROW;
  const roomRow = Math.floor(idx / ROOMS_PER_ROW);
  const s = TILE_SIZE * zoom;

  const contentW = CONTENT_TILES_W * s;
  const contentH = CONTENT_TILES_H * s;
  const w = canvas.width;
  const h = canvas.height;
  const contentOffsetX = (w - contentW) / 2;
  const contentOffsetY = (h - contentH) / 2;
  const roomX = contentOffsetX + (PAD_LEFT + roomCol * (ROOM_COLS + ROOM_GAP)) * s;
  const roomY = contentOffsetY + (PAD_TOP + roomRow * (ROOM_ROWS + ROOM_GAP)) * s;
  const roomCenterX = roomX + (ROOM_COLS * s) / 2;
  const roomCenterY = roomY + (ROOM_ROWS * s) / 2;
  const dpr = window.devicePixelRatio || 1;

  userZoom = 1.5;
  zoom = baseZoom * userZoom;
  panX = (w / 2 - roomCenterX) / dpr;
  panY = (h / 2 - roomCenterY) / dpr;
}

/** Return a PNG blob of the current canvas */
export function screenshot() {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/png");
  });
}

// ---- Game Loop ----

let lastTime = 0;

function gameLoop(time) {
  const dt = time - lastTime;
  lastTime = time;

  // Frame-rate independent particle animation, scaled by animationSpeed
  const frameDt = Math.min(dt, 100); // cap to 100ms to avoid jumps on tab-switch
  const scaledDt = frameDt * animSpeed;
  tickParticles(scaledDt / 16.7 * 0.012);
  if (scaledDt > 0) tick++;
  // Expire bubbles: every ~6 frames at 1x speed, faster at 2x, never at 0x
  if (animSpeed > 0 && tick % Math.max(1, Math.round(6 / animSpeed)) === 0) {
    expireBubbles();
  }

  // Tick roaming idle agents
  tickRoaming();

  render();
  requestAnimationFrame(gameLoop);
}

// ---- Background Pattern — mission-control ambient grid ----
function drawBackgroundPattern(w, h, colors) {
  const isDark = colors.bg.startsWith("#0") || colors.bg.startsWith("#1");
  const gridSize = 40 * zoom;

  // Subtle grid lines
  ctx.save();
  ctx.strokeStyle = isDark ? "rgba(30,60,90,0.18)" : "rgba(0,0,0,0.04)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 0; x < w; x += gridSize) {
    ctx.moveTo(Math.round(x) + 0.5, 0);
    ctx.lineTo(Math.round(x) + 0.5, h);
  }
  for (let y = 0; y < h; y += gridSize) {
    ctx.moveTo(0, Math.round(y) + 0.5);
    ctx.lineTo(w, Math.round(y) + 0.5);
  }
  ctx.stroke();

  // Accent dots at grid intersections
  ctx.fillStyle = isDark ? "rgba(0,212,255,0.06)" : "rgba(0,100,200,0.04)";
  for (let x = 0; x < w; x += gridSize) {
    for (let y = 0; y < h; y += gridSize) {
      ctx.fillRect(Math.round(x) - 1, Math.round(y) - 1, 2, 2);
    }
  }

  // Corner crosshairs — mission control framing
  const chSize = 12 * zoom;
  ctx.strokeStyle = isDark ? "rgba(0,212,255,0.12)" : "rgba(0,100,200,0.06)";
  ctx.lineWidth = 1.5;
  const corners = [[20, 20], [w - 20, 20], [20, h - 20], [w - 20, h - 20]];
  for (const [cx, cy] of corners) {
    ctx.beginPath();
    ctx.moveTo(cx - chSize, cy); ctx.lineTo(cx + chSize, cy);
    ctx.moveTo(cx, cy - chSize); ctx.lineTo(cx, cy + chSize);
    ctx.stroke();
  }

  ctx.restore();
}

function render() {
  if (!ctx) return;
  const w = canvas.width;
  const h = canvas.height;

  ctx.clearRect(0, 0, w, h);

  // Background — reads from active theme
  const colors = getCanvasColors();
  ctx.fillStyle = colors.bg;
  ctx.fillRect(0, 0, w, h);

  // Ambient background pattern — subtle blueprint/tech grid
  drawBackgroundPattern(w, h, colors);

  const s = TILE_SIZE * zoom;
  const dpr = window.devicePixelRatio || 1;

  // Center the FULL padded content area in the canvas, then position
  // the room grid at the PAD_LEFT / PAD_TOP offset within it.
  // This keeps zoom bounds and centering in perfect agreement.
  const contentW = CONTENT_TILES_W * s;
  const contentH = CONTENT_TILES_H * s;
  const contentOffsetX = Math.floor((w - contentW) / 2) + panX * dpr;
  const contentOffsetY = Math.floor((h - contentH) / 2) + panY * dpr;
  const offsetX = contentOffsetX + PAD_LEFT * s;
  const offsetY = contentOffsetY + PAD_TOP * s;
  // Room grid width (used by orchestrator zone, not for centering)
  const totalW = (ROOMS_PER_ROW * ROOM_COLS + ROOM_GAP) * s;

  // ---- Draw rooms ----
  const teamEntries = Object.entries(TEAMS);
  const drawables = [];

  for (let i = 0; i < teamEntries.length; i++) {
    const [teamId, team] = teamEntries[i];
    const roomCol = i % ROOMS_PER_ROW;
    const roomRow = Math.floor(i / ROOMS_PER_ROW);
    const rx = offsetX + roomCol * (ROOM_COLS + ROOM_GAP) * s;
    const ry = offsetY + roomRow * (ROOM_ROWS + ROOM_GAP) * s;

    drawRoom(rx, ry, teamId);
    drawRoomLabel(rx, ry, team, teamId);

    // Build drawables for z-sorting
    const items = buildRoomLayout(team, teamId);
    for (const item of items) {
      const ix = rx + item.col * s;
      const iy = ry + item.row * s;
      // No z-bonus: natural Y-order means desk/monitor draw ON TOP of agent
      const zY = iy;
      drawables.push({ type: item.type, x: ix, y: iy, zY, teamId, agent: item.agent, roaming: item.roaming });
    }
  }

  // ---- Draw orchestrator zone ----
  drawOrchestratorZone(offsetX, offsetY, totalW, s);

  // ---- Z-sort and draw all furniture + agents ----
  drawables.sort((a, b) => a.zY - b.zY);

  for (const d of drawables) {
    switch (d.type) {
      case "desk": drawSprite(DESK_SPRITE, d.x, d.y); break;
      case "monitor": drawSpriteWithGlow(MONITOR_SPRITE, d.x, d.y, d.teamId); break;
      case "chair": drawSprite(CHAIR_SPRITE, d.x, d.y); break;
      case "plant": drawSprite(PLANT_SPRITE, d.x, d.y); break;
      case "bookshelf": drawSprite(BOOKSHELF_SPRITE, d.x, d.y); break;
      case "whiteboard": drawSprite(WHITEBOARD_SPRITE, d.x, d.y); break;
      case "easel": drawSprite(EASEL_SPRITE, d.x, d.y); break;
      case "box": drawSprite(BOX_SPRITE, d.x, d.y); break;
      case "trophy": drawSprite(TROPHY_SPRITE, d.x, d.y); break;
      case "agent": drawAgent(d.x, d.y, d.agent, d.teamId, d.roaming); break;
    }
  }

  // ---- Draw particles ----
  drawParticles();

  // ---- Draw speech bubbles ----
  drawAllBubbles();

  // ---- Tooltip ----
  drawTooltip();

  // ---- Zoom/Pan hint (bottom-left) ----
  if (userZoom !== 1 || panX !== 0 || panY !== 0) {
    ctx.save();
    ctx.font = '11px "JetBrains Mono", monospace';
    ctx.fillStyle = "#475569";
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.fillText(`${Math.round(userZoom * 100)}% · dbl-click to fit`, 12, h - 8);
    ctx.restore();
  } else {
    ctx.save();
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.fillStyle = "#334155";
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.fillText("scroll to zoom · shift-drag to pan · dbl-click to fit", 12, h - 8);
    ctx.restore();
  }
}

// ---- Room Rendering ----

function drawRoom(rx, ry, teamId) {
  const s = TILE_SIZE * zoom;
  const style = TEAM_STYLES[teamId] || TEAM_STYLES.research;

  // Checkerboard floor
  for (let r = 0; r < ROOM_ROWS; r++) {
    for (let c = 0; c < ROOM_COLS; c++) {
      ctx.fillStyle = (r + c) % 2 === 0 ? style.floor1 : style.floor2;
      ctx.fillRect(rx + c * s, ry + r * s, s, s);
    }
  }

  // Walls
  ctx.fillStyle = style.wall;
  ctx.fillRect(rx, ry, ROOM_COLS * s, zoom * 4);
  ctx.fillRect(rx, ry, zoom * 4, ROOM_ROWS * s);
  ctx.fillRect(rx + ROOM_COLS * s - zoom * 4, ry, zoom * 4, ROOM_ROWS * s);
  ctx.fillRect(rx, ry + ROOM_ROWS * s - zoom * 4, ROOM_COLS * s, zoom * 4);

  // Accent glow on top
  ctx.fillStyle = style.accent;
  ctx.globalAlpha = 0.5;
  ctx.fillRect(rx, ry, ROOM_COLS * s, zoom * 2);
  ctx.globalAlpha = 1;

  // Active stage highlight — subtle glow on the whole room
  const pipeline = getPipeline();
  const activeTeam = STAGE_TO_TEAM[pipeline.stage];
  if (activeTeam === teamId) {
    ctx.save();
    ctx.globalAlpha = 0.04 + 0.02 * Math.sin(tick * 0.05);
    ctx.fillStyle = style.accent;
    ctx.fillRect(rx, ry, ROOM_COLS * s, ROOM_ROWS * s);
    ctx.restore();
  }
}

function drawRoomLabel(rx, ry, team, teamId) {
  const s = TILE_SIZE * zoom;
  const style = TEAM_STYLES[teamId];

  // Count active agents in this team
  const agentStates = team.agents.map(n => getAgent(n)).filter(Boolean);
  const activeCount = agentStates.filter(a => a.status === "active").length;
  const totalCount = agentStates.length;

  // Department name — big, readable
  const nameSize = Math.max(11, Math.round(12 * zoom * 0.7));
  ctx.save();
  ctx.font = `900 ${nameSize}px "FS Pixel Sans Unicode", "Press Start 2P", monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";

  const cx = rx + (ROOM_COLS * s) / 2;
  const cy = ry + nameSize * 0.9;
  const text = team.label.toUpperCase();
  const metrics = ctx.measureText(text);
  const padX = nameSize * 0.7;
  const padY = nameSize * 0.4;

  // Background pill
  ctx.globalAlpha = 0.7;
  ctx.fillStyle = "#0a0e17";
  const rw = metrics.width + padX * 2;
  const rh = nameSize + padY * 2;
  ctx.beginPath();
  ctx.roundRect(cx - rw / 2, cy - rh / 2, rw, rh, rh / 2);
  ctx.fill();

  // Text
  ctx.globalAlpha = 1;
  ctx.fillStyle = style.accent;
  ctx.fillText(text, cx, cy);

  // Activity counter badge — "2/4 active" to the right of the label
  const badgeSize = Math.max(7, Math.round(7 * zoom * 0.55));
  ctx.font = `700 ${badgeSize}px "JetBrains Mono", monospace`;
  const badgeText = `${activeCount}/${totalCount}`;
  const badgeW = ctx.measureText(badgeText).width + badgeSize * 1.2;
  const badgeH = badgeSize * 1.6;
  const badgeX = cx + rw / 2 + badgeSize * 0.4;
  const badgeY = cy - badgeH / 2;

  // Badge background
  ctx.globalAlpha = 0.8;
  ctx.fillStyle = activeCount > 0 ? style.accent : "#1e293b";
  ctx.globalAlpha = activeCount > 0 ? 0.2 : 0.6;
  ctx.beginPath();
  ctx.roundRect(badgeX, badgeY, badgeW, badgeH, badgeH / 2);
  ctx.fill();

  // Badge text
  ctx.globalAlpha = 1;
  ctx.textAlign = "center";
  ctx.fillStyle = activeCount > 0 ? style.accent : "#475569";
  ctx.fillText(badgeText, badgeX + badgeW / 2, cy);

  // Role subtitle
  const roleSize = Math.max(8, Math.round(8 * zoom * 0.55));
  ctx.font = `${roleSize}px "JetBrains Mono", monospace`;
  ctx.textAlign = "center";
  ctx.fillStyle = "#64748b";
  ctx.globalAlpha = 0.8;
  ctx.fillText(team.role, cx, cy + nameSize * 0.8);

  ctx.restore();
}

// ---- Orchestrator Zone ----

function drawOrchestratorZone(offsetX, offsetY, totalW, s) {
  const orch = getOrchestrator();
  const pipeline = getPipeline();

  // Zone position: between the two rows of rooms
  const zy = offsetY + ROOM_ROWS * s;
  const zx = offsetX;
  const zw = totalW;
  const zh = ROOM_GAP * s;
  const cx = zx + zw / 2;

  // Background — dark panel with subtle gradient
  ctx.save();
  const grad = ctx.createLinearGradient(zx, zy, zx, zy + zh);
  grad.addColorStop(0, "rgba(10,15,25,0.9)");
  grad.addColorStop(0.5, "rgba(13,17,23,0.95)");
  grad.addColorStop(1, "rgba(10,15,25,0.9)");
  ctx.fillStyle = grad;
  ctx.fillRect(zx, zy, zw, zh);

  // Subtle border glow
  ctx.strokeStyle = "rgba(0,212,255,0.12)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(zx, zy); ctx.lineTo(zx + zw, zy);
  ctx.moveTo(zx, zy + zh); ctx.lineTo(zx + zw, zy + zh);
  ctx.stroke();

  // ---- Orchestrator title ----
  const titleSize = Math.max(9, Math.round(9 * zoom * 0.6));
  ctx.font = `900 ${titleSize}px "FS Pixel Sans Unicode", "Press Start 2P", monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const titleY = zy + zh * 0.2;

  const orchActive = orch.status === "active" || orch.status === "waiting";
  ctx.fillStyle = orchActive ? "#00d4ff" : "#475569";
  if (orchActive) { ctx.shadowColor = "#00d4ff"; ctx.shadowBlur = 10; }
  ctx.fillText("⬡ ORCHESTRATOR", cx, titleY);
  ctx.shadowBlur = 0;

  // ---- Timeline — node-based stage progression ----
  const timelineW = zw * 0.85;
  const timelineX = cx - timelineW / 2;
  const timelineY = zy + zh * 0.5;
  const nodeR = Math.max(5, zoom * 2);
  const stageCount = PIPELINE_STAGES.length;
  const stageSpacing = timelineW / (stageCount - 1);
  const currentIdx = PIPELINE_STAGES.indexOf(pipeline.stage);

  // Draw connecting track line (background)
  ctx.strokeStyle = "#1e293b";
  ctx.lineWidth = Math.max(2, zoom * 0.8);
  ctx.beginPath();
  ctx.moveTo(timelineX, timelineY);
  ctx.lineTo(timelineX + timelineW, timelineY);
  ctx.stroke();

  // Draw completed progress line
  if (currentIdx >= 0) {
    const progressX = timelineX + currentIdx * stageSpacing;
    const progressGrad = ctx.createLinearGradient(timelineX, 0, progressX, 0);
    progressGrad.addColorStop(0, "#00d4ff");
    progressGrad.addColorStop(1, orchActive ? "#00d4ff" : "#475569");
    ctx.strokeStyle = progressGrad;
    ctx.lineWidth = Math.max(3, zoom * 1.2);
    ctx.beginPath();
    ctx.moveTo(timelineX, timelineY);
    ctx.lineTo(progressX, timelineY);
    ctx.stroke();
  }

  // Draw stage nodes
  const labelSize = Math.max(6, Math.round(6 * zoom * 0.5));
  ctx.textBaseline = "top";
  ctx.font = `600 ${labelSize}px "JetBrains Mono", monospace`;

  for (let i = 0; i < stageCount; i++) {
    const nx = timelineX + i * stageSpacing;
    const stage = PIPELINE_STAGES[i];
    const activeTeam = STAGE_TO_TEAM[stage];
    const color = activeTeam ? TEAMS[activeTeam]?.color || "#475569" : "#ffae00";
    const isCompleted = i < currentIdx;
    const isActive = i === currentIdx;
    const isFuture = i > currentIdx || currentIdx < 0;

    // Node circle
    ctx.beginPath();
    ctx.arc(nx, timelineY, nodeR, 0, Math.PI * 2);

    if (isCompleted) {
      // Filled with team color
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.8;
      ctx.fill();
      // Checkmark
      ctx.globalAlpha = 1;
      ctx.strokeStyle = "#0d1117";
      ctx.lineWidth = Math.max(1.5, zoom * 0.5);
      ctx.beginPath();
      ctx.moveTo(nx - nodeR * 0.4, timelineY);
      ctx.lineTo(nx - nodeR * 0.1, timelineY + nodeR * 0.35);
      ctx.lineTo(nx + nodeR * 0.45, timelineY - nodeR * 0.3);
      ctx.stroke();
    } else if (isActive) {
      // Pulsing glow ring + filled center
      const pulse = 0.6 + 0.4 * Math.sin(tick * 0.08);
      ctx.shadowColor = color;
      ctx.shadowBlur = 12 * pulse;
      ctx.fillStyle = color;
      ctx.globalAlpha = pulse;
      ctx.fill();
      ctx.shadowBlur = 0;
      // Outer ring
      ctx.globalAlpha = 1;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(nx, timelineY, nodeR + 3, 0, Math.PI * 2);
      ctx.stroke();
    } else {
      // Empty future node
      ctx.fillStyle = "#0d1117";
      ctx.globalAlpha = 1;
      ctx.fill();
      ctx.strokeStyle = "#334155";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    // Stage label below node
    ctx.textAlign = "center";
    const label = stage.replace(/_/g, " ");
    const shortLabel = label.length > 10 ? label.split(" ").map(w => w.slice(0, 4)).join(" ") : label;
    ctx.fillStyle = isActive ? color : isCompleted ? "#64748b" : "#334155";
    ctx.fillText(shortLabel.toUpperCase(), nx, timelineY + nodeR + 4);
  }

  // ---- Active stage marker triangle ----
  if (currentIdx >= 0) {
    const mx = timelineX + currentIdx * stageSpacing;
    const stage = PIPELINE_STAGES[currentIdx];
    const activeTeam = STAGE_TO_TEAM[stage];
    const markerColor = activeTeam ? TEAMS[activeTeam]?.color || "#ffae00" : "#ffae00";
    ctx.fillStyle = markerColor;
    ctx.beginPath();
    ctx.moveTo(mx, timelineY - nodeR - 5);
    ctx.lineTo(mx - 4, timelineY - nodeR - 11);
    ctx.lineTo(mx + 4, timelineY - nodeR - 11);
    ctx.closePath();
    ctx.fill();
  }

  // ---- Orchestrator message at bottom ----
  if (orch.message) {
    const msgSize = Math.max(7, Math.round(7 * zoom * 0.5));
    ctx.font = `${msgSize}px "JetBrains Mono", monospace`;
    ctx.fillStyle = "#64748b";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(orch.message.slice(0, 80), cx, zy + zh * 0.85);
  }

  ctx.restore();
}

// ---- Room Layout ----

function buildRoomLayout(team, teamId) {
  const agents = team.agents;
  const items = [];

  // Adaptive centering: compute grid dimensions then center in room
  const cols = Math.min(agents.length, 2);          // max 2 per row
  const rows = Math.ceil(agents.length / 2);
  const deskSpacingX = 4;                            // cols between desks
  const deskSpacingY = 2.4;                          // rows between desks
  const agentOffset = 1.9;                           // agent sits behind monitor (sweet spot)
  const gridW = cols > 1 ? deskSpacingX : 0;         // total width of desk cluster
  const gridH = (rows - 1) * deskSpacingY + agentOffset; // include agent above top desk
  const startCol = (ROOM_COLS - gridW - 2) / 2;      // center horizontally (-2 for desk width)
  const startRow = (ROOM_ROWS - gridH - 1) / 2 + agentOffset; // center the full unit, desk anchor

  for (let i = 0; i < agents.length; i++) {
    const col = startCol + (i % 2) * deskSpacingX;
    const row = startRow + Math.floor(i / 2) * deskSpacingY;
    // Agent centered with monitor on desk, facing viewer
    const deskCenterCol = col + 0.4;  // monitor col = desk center reference
    const agentDeskRow = row - agentOffset;

    // Register desk position for roaming system
    initRoam(agents[i], deskCenterCol, agentDeskRow, teamId);

    // Use roaming position for idle agents
    const agent = getAgent(agents[i]);
    const rs = roamState[agents[i]];
    const isRoaming = rs && agent?.status === "idle" && rs.state !== "seated";
    const agentCol = isRoaming ? rs.col : deskCenterCol;
    const agentRow = isRoaming ? rs.row : agentDeskRow;

    items.push({ type: "agent", col: agentCol, row: agentRow, agent: agents[i], roaming: isRoaming });
    items.push({ type: "monitor", col: deskCenterCol, row: row - 0.15 });
    items.push({ type: "desk", col, row });
  }

  // Decorations — spread to room corners
  const teamDecor = {
    research:  "whiteboard",
    design:    "easel",
    commerce:  "box",
    learning:  "trophy",
  };
  const decor = teamDecor[teamId];
  items.push({ type: "plant", col: 0.5, row: 0.5 });                    // top-left corner
  if (decor) {
    items.push({ type: decor, col: ROOM_COLS - 1.5, row: 0.5 });        // top-right corner
  }
  items.push({ type: "bookshelf", col: 0.5, row: ROOM_ROWS - 2.25 });  // bottom-left corner (inside room)

  // Register furniture positions for collision detection
  _registerFurniture(teamId, items);

  return items;
}

// ---- Sprite Drawing ----

function drawSprite(spriteData, x, y) {
  ctx.imageSmoothingEnabled = false;  // crisp pixel art
  const cached = getCachedSprite(spriteData, zoom);
  ctx.drawImage(cached, Math.round(x), Math.round(y));
  ctx.imageSmoothingEnabled = true;   // restore for text
}

function drawSpriteWithGlow(spriteData, x, y, teamId) {
  const team = TEAMS[teamId];
  const hasActive = team && team.agents.some((n) => {
    const a = getAgent(n);
    return a && a.status === "active";
  });

  if (hasActive) {
    const style = TEAM_STYLES[teamId];
    ctx.save();
    ctx.globalAlpha = 0.35;
    ctx.fillStyle = style?.accent || "#00d4ff";
    const cached = getCachedSprite(spriteData, zoom);
    ctx.fillRect(
      Math.round(x) + zoom * 3,
      Math.round(y) + zoom * 2,
      cached.width - zoom * 6,
      cached.height * 0.5
    );
    ctx.restore();
  }
  drawSprite(spriteData, x, y);
}

// Disable smoothing for a sprite draw call, then re-enable
function drawSpriteNoSmooth(spriteCanvas, x, y) {
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(spriteCanvas, Math.round(x), Math.round(y));
  ctx.imageSmoothingEnabled = true;
}

// ---- Agent Drawing ----

function drawAgent(x, y, agentName, teamId, roaming) {
  const agent = getAgent(agentName);
  if (!agent) return;

  const paletteIdx = getPaletteIndex(agentName);
  const rs = roamState[agentName];
  const isMoving = roaming && rs && (rs.state === "walking" || rs.state === "returning" || rs.state === "activity");
  const isRunning = roaming && rs && rs.state === "returning";
  const mirrorX = isMoving && rs.direction === "left";

  // Pick sprite: directional walk frame for moving/activity, normal desk frame otherwise
  // Running agents get faster animation cycle
  const frame = isMoving
    ? getWalkFrame(paletteIdx, rs.direction, tick, isRunning)
    : getCharFrame(paletteIdx, agent.status, tick);

  // Agent is positioned behind desk — no offset needed
  let drawY = y;

  if (frame) {
    const cached = getCachedSprite(frame, zoom);

    // Glow effect — different per state
    if (agent.status === "active" || agent.status === "waiting") {
      ctx.save();
      const accent = TEAM_STYLES[teamId]?.accent || "#00d4ff";
      ctx.globalAlpha = 0.2 + 0.1 * Math.sin(tick * 0.08);
      ctx.fillStyle = accent;
      ctx.beginPath();
      ctx.arc(
        Math.round(x) + cached.width / 2,
        Math.round(drawY) + cached.height / 2,
        cached.width * 0.75,
        0,
        Math.PI * 2
      );
      ctx.fill();
      ctx.restore();
    } else if (agent.status === "error") {
      // Red pulsing flash for error
      ctx.save();
      ctx.globalAlpha = 0.25 + 0.2 * Math.sin(tick * 0.15);
      ctx.fillStyle = "#f85149";
      ctx.beginPath();
      ctx.arc(
        Math.round(x) + cached.width / 2,
        Math.round(drawY) + cached.height / 2,
        cached.width * 0.85,
        0,
        Math.PI * 2
      );
      ctx.fill();
      ctx.restore();
    }

    // Draw sprite — mirror horizontally for "left" direction
    if (mirrorX) {
      ctx.save();
      ctx.translate(Math.round(x) + cached.width, 0);
      ctx.scale(-1, 1);
      drawSpriteNoSmooth(cached, 0, drawY);
      ctx.restore();
    } else {
      drawSpriteNoSmooth(cached, x, drawY);
    }

    // Running urgency effects — exclamation + dust puffs
    if (isRunning) {
      const cx = Math.round(x) + cached.width / 2;
      const cy = Math.round(drawY);
      const markSize = Math.max(10, Math.round(zoom * 5));

      // Exclamation mark above head — bouncing
      ctx.save();
      const bounce = Math.sin(tick * 0.3) * zoom * 1.5;
      ctx.font = `900 ${markSize}px "JetBrains Mono", monospace`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#ffae00";
      ctx.shadowColor = "#ffae00";
      ctx.shadowBlur = 6;
      ctx.fillText("!", cx, cy - zoom * 2 + bounce);
      ctx.shadowBlur = 0;
      ctx.restore();

      // Dust puffs behind the agent — 3 small circles that trail
      ctx.save();
      ctx.globalAlpha = 0.4;
      const dustDir = rs.direction === "right" ? -1 : rs.direction === "left" ? 1 : 0;
      const dustDirY = rs.direction === "down" ? -1 : rs.direction === "up" ? 1 : 0;
      for (let p = 0; p < 3; p++) {
        const age = ((tick + p * 7) % 20) / 20; // 0→1 lifecycle
        const puffR = zoom * (1.5 + age * 2);
        const puffAlpha = 0.5 * (1 - age);
        const puffX = cx + dustDir * (zoom * 3 + age * zoom * 6) + Math.sin(tick * 0.2 + p) * zoom;
        const puffY = cy + cached.height * 0.8 + dustDirY * (zoom * 2 + age * zoom * 4);
        ctx.globalAlpha = puffAlpha;
        ctx.fillStyle = "#8b8b8b";
        ctx.beginPath();
        ctx.arc(puffX, puffY, puffR, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    // Error exclamation mark overlay
    if (agent.status === "error") {
      const errSize = Math.max(10, Math.round(zoom * 5));
      ctx.save();
      ctx.font = `900 ${errSize}px "JetBrains Mono", monospace`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#f85149";
      ctx.shadowColor = "#f85149";
      ctx.shadowBlur = 8;
      ctx.fillText("!", Math.round(x) + cached.width / 2, Math.round(drawY) + cached.height * 0.25);
      ctx.shadowBlur = 0;
      ctx.restore();
    }
  }

  // Always record position (fallback dims when sprites not loaded)
  const dpr = window.devicePixelRatio || 1;
  const spriteW = frame ? getCachedSprite(frame, zoom).width : TILE_SIZE * zoom;
  const spriteH = frame ? getCachedSprite(frame, zoom).height : TILE_SIZE * 2 * zoom;
  agentPositions[agentName] = {
    x: Math.round(x) / dpr,
    y: Math.round(drawY) / dpr,
    w: spriteW / dpr,
    h: spriteH / dpr,
    cx: Math.round(x) + spriteW / 2,
    cy: Math.round(drawY) + spriteH / 2,
  };

  // ---- Agent Name + Status Card — positioned to the RIGHT of the sprite ----
  const accent = TEAM_STYLES[teamId]?.accent || "#fff";
  const displayName = agentName.split("-").map(w => w[0].toUpperCase() + w.slice(1)).join(" ");
  const labelX = Math.round(x) + spriteW + zoom * 2;
  const labelY = Math.round(drawY) + spriteH * 0.15;

  ctx.save();
  ctx.textAlign = "left";
  ctx.textBaseline = "top";

  if (agent.status === "active" || agent.status === "waiting") {
    // ---- Active/Waiting: draw a mini status card to the right ----
    const cardNameSize = Math.max(7, Math.round(zoom * 3.2));
    const cardTaskSize = Math.max(6, Math.round(zoom * 2.4));
    ctx.font = `700 ${cardNameSize}px "JetBrains Mono", monospace`;
    const nameW = ctx.measureText(displayName).width;

    // Task text (truncated)
    const taskText = agent.task ? agent.task.slice(0, 30) + (agent.task.length > 30 ? "…" : "") : "";
    ctx.font = `${cardTaskSize}px "JetBrains Mono", monospace`;
    const taskW = taskText ? ctx.measureText(taskText).width : 0;

    const cardPadX = zoom * 2;
    const cardPadY = zoom * 1.2;
    const cardW = Math.max(nameW, taskW) + cardPadX * 2 + zoom * 3;
    const cardH = cardNameSize + (taskText ? cardTaskSize + 3 : 0) + cardPadY * 2;
    const cardX = labelX;
    const cardY = labelY;

    // Card background
    ctx.globalAlpha = 0.9;
    ctx.fillStyle = "#0d1117";
    ctx.beginPath();
    ctx.roundRect(cardX, cardY, cardW, cardH, zoom * 1.2);
    ctx.fill();

    // Accent left stripe
    ctx.fillStyle = accent;
    ctx.globalAlpha = agent.status === "active" ? 0.9 : 0.5;
    ctx.fillRect(cardX, cardY + zoom, zoom * 1.2, cardH - zoom * 2);

    // Agent name
    ctx.globalAlpha = 1;
    ctx.font = `700 ${cardNameSize}px "JetBrains Mono", monospace`;
    ctx.fillStyle = agent.status === "active" ? accent : "#ffae00";
    ctx.fillText(displayName, cardX + cardPadX + zoom * 1.5, cardY + cardPadY);

    // Task text
    if (taskText) {
      ctx.font = `${cardTaskSize}px "JetBrains Mono", monospace`;
      ctx.fillStyle = "#94a3b8";
      ctx.fillText(taskText, cardX + cardPadX + zoom * 1.5, cardY + cardPadY + cardNameSize + 2);
    }

    // Pulsing status dot
    const dotR = Math.max(2.5, zoom * 0.8);
    ctx.fillStyle = accent;
    ctx.globalAlpha = 0.7 + 0.3 * Math.sin(tick * 0.1);
    ctx.shadowColor = accent;
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.arc(cardX + cardW - cardPadX, cardY + cardPadY + cardNameSize / 2, dotR, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  } else {
    // ---- Idle/error: compact name label to the right (wraps if 2+ words) ----
    const nameSize = Math.max(7, Math.round(zoom * 3));
    ctx.font = `600 ${nameSize}px "JetBrains Mono", monospace`;
    ctx.fillStyle = agent.status === "error" ? "#f85149" : "#475569";
    const words = displayName.split(" ");
    const maxLabelW = zoom * 28;
    let lines = [];
    if (words.length > 1 && ctx.measureText(displayName).width > maxLabelW) {
      // Wrap: first word on line 1, rest on line 2
      lines = [words[0], words.slice(1).join(" ")];
    } else {
      lines = [displayName];
    }
    for (let li = 0; li < lines.length; li++) {
      ctx.fillText(lines[li], labelX, labelY + li * (nameSize + 1));
    }

    // Status dot next to last line
    const dotR = Math.max(2, zoom * 0.6);
    const lastLine = lines[lines.length - 1];
    const lastLineW = ctx.measureText(lastLine).width;
    const dotY = labelY + (lines.length - 1) * (nameSize + 1) + nameSize / 2;
    const dotColor = agent.status === "error" ? "#f85149" : "#334155";
    ctx.fillStyle = dotColor;
    ctx.beginPath();
    ctx.arc(labelX + lastLineW + dotR + 3, dotY, dotR, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();
}

// ---- Speech Bubbles (word-wrapped, persistent) ----

function drawAllBubbles() {
  const bubbles = getBubbles();
  const now = Date.now();

  for (const bubble of bubbles) {
    const pos = agentPositions[bubble.agent];
    if (!pos) continue;

    const dpr = window.devicePixelRatio || 1;
    const elapsed = now - bubble.createdAt;
    const remaining = bubble.duration - elapsed;

    // Fade out in last 1000ms
    let alpha = 1;
    if (remaining < 1000) alpha = remaining / 1000;
    if (alpha <= 0) continue;

    // Fade in over first 300ms
    if (elapsed < 300) alpha = Math.min(alpha, elapsed / 300);

    const bx = pos.cx;
    const by = pos.cy - (pos.h * dpr) * 0.4;

    drawWordWrappedBubble(bx, by, bubble.text, bubble.type, alpha);
  }
}

function drawWordWrappedBubble(x, y, text, type, alpha) {
  const fontSize = Math.max(8, Math.round(zoom * 3));
  const maxWidth = Math.max(100, zoom * 55);
  const lineHeight = fontSize * 1.3;
  const padding = zoom * 3;

  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.font = `${fontSize}px "JetBrains Mono", monospace`;

  // Word wrap
  const words = text.split(" ");
  const lines = [];
  let currentLine = "";
  for (const word of words) {
    const test = currentLine ? currentLine + " " + word : word;
    if (ctx.measureText(test).width > maxWidth && currentLine) {
      lines.push(currentLine);
      currentLine = word;
    } else {
      currentLine = test;
    }
  }
  if (currentLine) lines.push(currentLine);
  // Max 3 lines
  if (lines.length > 3) {
    lines.length = 3;
    lines[2] = lines[2].slice(0, -3) + "...";
  }

  const maxLineW = Math.max(...lines.map(l => ctx.measureText(l).width));
  const bw = maxLineW + padding * 2;
  const bh = lines.length * lineHeight + padding * 2;
  const bx = x - bw / 2;
  const by = y - bh - zoom * 4;

  // Bubble background
  const colors = {
    thinking: { bg: "#111827", border: "#00d4ff", text: "#c8dbe6" },
    receiving: { bg: "#1a0c20", border: "#ff6ec7", text: "#e8c8d8" },
    done: { bg: "#0c1a10", border: "#39ff14", text: "#c8e8c8" },
    error: { bg: "#1a0808", border: "#f85149", text: "#f8c8c8" },
  };
  const c = colors[type] || colors.thinking;

  ctx.fillStyle = c.bg;
  ctx.globalAlpha = alpha * 0.92;
  ctx.beginPath();
  ctx.roundRect(bx, by, bw, bh, zoom * 2);
  ctx.fill();

  // Border
  ctx.strokeStyle = c.border;
  ctx.lineWidth = zoom * 0.6;
  ctx.globalAlpha = alpha * 0.7;
  ctx.stroke();

  // Tail
  ctx.fillStyle = c.bg;
  ctx.globalAlpha = alpha * 0.92;
  ctx.beginPath();
  ctx.moveTo(x - zoom * 3, by + bh);
  ctx.lineTo(x, by + bh + zoom * 4);
  ctx.lineTo(x + zoom * 3, by + bh);
  ctx.fill();

  // Text lines
  ctx.globalAlpha = alpha;
  ctx.fillStyle = c.text;
  ctx.textBaseline = "top";
  ctx.textAlign = "left";
  for (let i = 0; i < lines.length; i++) {
    ctx.fillText(lines[i], bx + padding, by + padding + i * lineHeight);
  }

  // Type indicator
  const icons = { thinking: "💭", receiving: "📨", done: "✓", error: "⚠" };
  ctx.font = `${fontSize - 1}px monospace`;
  ctx.fillStyle = c.border;
  ctx.textAlign = "right";
  ctx.fillText(icons[type] || "", bx + bw - padding * 0.5, by + padding * 0.3);

  ctx.restore();
}

// ---- Communication Particles ----

function drawParticles() {
  const particles = getParticles();
  if (particles.length === 0) return;

  ctx.save();
  for (const p of particles) {
    const from = agentPositions[p.fromAgent];
    const to = agentPositions[p.toAgent];
    if (!from || !to) continue;

    const t = p.progress;
    // Cubic ease
    const ease = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

    const px = from.cx + (to.cx - from.cx) * ease;
    const py = from.cy + (to.cy - from.cy) * ease - Math.sin(t * Math.PI) * zoom * 15;

    // Glow trail
    const trailAlpha = Math.max(0, 1 - t * 1.2);
    ctx.globalAlpha = trailAlpha * 0.4;
    ctx.fillStyle = p.color;
    ctx.beginPath();
    ctx.arc(px, py, zoom * 3, 0, Math.PI * 2);
    ctx.fill();

    // Core dot
    ctx.globalAlpha = trailAlpha;
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.arc(px, py, zoom * 1.5, 0, Math.PI * 2);
    ctx.fill();

    // Tag label alongside particle
    if (p.tag && t > 0.15 && t < 0.85) {
      const tagSize = Math.max(6, Math.round(zoom * 2.5));
      ctx.font = `600 ${tagSize}px "JetBrains Mono", monospace`;
      ctx.textAlign = "center";
      ctx.fillStyle = p.color;
      ctx.globalAlpha = trailAlpha * 0.8;
      ctx.fillText(p.tag, px, py - zoom * 4);
    }

    // Connection line (faint)
    ctx.globalAlpha = trailAlpha * 0.12;
    ctx.strokeStyle = p.color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(from.cx, from.cy);
    ctx.lineTo(to.cx, to.cy);
    ctx.stroke();
  }
  ctx.restore();
}

// ---- Palette ----
const paletteMap = {};
let nextPalette = 0;

function getPaletteIndex(agentName) {
  if (paletteMap[agentName] === undefined) {
    paletteMap[agentName] = nextPalette;
    nextPalette = (nextPalette + 1) % 6;
  }
  return paletteMap[agentName];
}

// ---- Mouse/Hover ----

function onMouseMove(e) {
  const rect = canvas.getBoundingClientRect();
  mouseX = e.clientX - rect.left;
  mouseY = e.clientY - rect.top;
  detectHover();
}

function detectHover() {
  hoveredAgent = null;
  for (const [name, pos] of Object.entries(agentPositions)) {
    if (mouseX >= pos.x && mouseX <= pos.x + pos.w &&
        mouseY >= pos.y && mouseY <= pos.y + pos.h) {
      hoveredAgent = name;
      break;
    }
  }
}

function drawTooltip() {
  if (!hoveredAgent) {
    const tip = document.getElementById("tooltip");
    if (tip) tip.classList.remove("tooltip--visible");
    return;
  }
  const agent = getAgent(hoveredAgent);
  if (!agent) return;
  const tip = document.getElementById("tooltip");
  if (!tip) return;

  const accent = TEAM_STYLES[agent.team]?.accent || "#00d4ff";
  const role = AGENT_ROLES[hoveredAgent] || "";
  const displayName = hoveredAgent.split("-").map(w => w[0].toUpperCase() + w.slice(1)).join(" ");

  tip.innerHTML = `
    <div class="tooltip__name" style="color:${accent}">${displayName}</div>
    <div class="tooltip__row">${role}</div>
    <div class="tooltip__row">Status: <strong style="color:${agent.status === 'active' ? accent : agent.status === 'error' ? '#f85149' : '#94a3b8'}">${agent.status.toUpperCase()}</strong></div>
    ${agent.task ? `<div class="tooltip__row">Task: ${escapeHtml(agent.task)}</div>` : ""}
    <div class="tooltip__row">Cost: $${agent.cost.toFixed(4)}</div>
    <div class="tooltip__row" style="color:${accent}">Team: ${escapeHtml(TEAMS[agent.team]?.label || agent.team)}</div>
  `;
  tip.classList.add("tooltip--visible");

  // Position tooltip avoiding edge overflow
  let tx = mouseX + 16;
  let ty = mouseY - 10;
  const tipRect = tip.getBoundingClientRect();
  if (tx + tipRect.width > window.innerWidth - 10) tx = mouseX - tipRect.width - 16;
  if (ty + tipRect.height > window.innerHeight - 10) ty = mouseY - tipRect.height - 10;

  tip.style.left = tx + "px";
  tip.style.top = ty + "px";
  tip.style.transform = "none";
}

// ---- Sidebar DOM rendering ----

export function renderPipeline() {
  if (!pipelineContainer) return;
  const pipeline = getPipeline();
  const idx = PIPELINE_STAGES.indexOf(pipeline.stage);
  pipelineContainer.innerHTML = PIPELINE_STAGES.map((s, i) => {
    let cls = "pending", icon = "○";
    if (i < idx) { cls = "completed"; icon = "●"; }
    else if (i === idx) { cls = s === "human_approval" ? "waiting" : "active"; icon = "▸"; }
    const activeTeam = STAGE_TO_TEAM[s];
    const teamColor = activeTeam && TEAMS[activeTeam] ? TEAMS[activeTeam].color : "#ffae00";
    const style = i === idx ? `color:${teamColor}` : "";
    return `<div class="stage stage--${cls}" style="${style}"><span class="stage__icon">${icon}</span><span class="stage__label">${s.replace(/_/g, " ")}</span></div>`;
  }).join("");

  if (runsContainer) {
    if (!pipeline.runs?.length) {
      runsContainer.innerHTML = '<span class="runs__empty">No active runs</span>';
    } else {
      const recent = pipeline.runs.slice(-5);
      const hidden = pipeline.runs.length - recent.length;
      let html = "";
      if (hidden > 0) {
        html += `<div class="runs__overflow">+${hidden} older run${hidden > 1 ? "s" : ""} hidden</div>`;
      }
      html += recent.map(r =>
        `<div class="run-item" title="${r.name}\nStage: ${r.stage || "—"}\nStatus: ${r.status || "active"}">` +
        `<span class="run-item__status run-item__status--${r.status || "active"}"></span>` +
        `<span class="run-item__name">${r.name}</span>` +
        `<span class="run-item__stage">${(r.stage || "—").replace(/_/g, " ")}</span>` +
        `</div>`
      ).join("");
      runsContainer.innerHTML = html;
    }
  }
}

// Track which teams are collapsed — collapsed by default so Cost is always visible
const _collapsedTeams = new Set(["research", "design", "commerce", "learning"]);

export function renderAgentActivity() {
  if (!agentActivityContainer) return;
  let html = "";
  for (const [teamId, team] of Object.entries(TEAMS)) {
    const isCollapsed = _collapsedTeams.has(teamId);
    const activeCount = team.agents.filter(n => {
      const a = getAgent(n);
      return a?.status && a.status !== "idle";
    }).length;
    const countLabel = activeCount > 0 ? `${activeCount}/${team.agents.length}` : `${team.agents.length}`;

    html += `<div class="activity-team ${isCollapsed ? "activity-team--collapsed" : ""}" data-team-id="${teamId}">
      <div class="activity-team__header">
        <span class="activity-team__chevron">▼</span>
        <span class="activity-team__name" style="color:var(--${teamId})">${team.label}</span>
        <span class="activity-team__count">${countLabel}</span>
      </div>
      <div class="activity-team__agents">`;
    for (const agentName of team.agents) {
      const agent = getAgent(agentName);
      const status = agent?.status || "idle";
      const displayName = agentName.replace(/-/g, " ");
      html += `<div class="activity-agent" data-agent="${agentName}">
        <span class="activity-agent__dot" style="color:var(--${status})">●</span>
        <span class="activity-agent__name">${displayName}</span>
        <span class="activity-agent__status">${status}</span>
      </div>`;
    }
    html += `</div></div>`;
  }
  agentActivityContainer.innerHTML = html;

  // Bind collapse toggles (delegated)
  agentActivityContainer.querySelectorAll(".activity-team__header").forEach(header => {
    header.addEventListener("click", (e) => {
      e.stopPropagation();
      const teamEl = header.closest(".activity-team");
      const tid = teamEl.dataset.teamId;
      if (_collapsedTeams.has(tid)) {
        _collapsedTeams.delete(tid);
        teamEl.classList.remove("activity-team--collapsed");
      } else {
        _collapsedTeams.add(tid);
        teamEl.classList.add("activity-team--collapsed");
      }
    });
  });
}

export function renderCost() {
  if (costContainer) costContainer.textContent = "$" + getTotalCost().toFixed(4);
}

export function renderEvents() {
  if (!eventLogContainer) return;

  // Read log filter values
  const searchEl = document.getElementById("events-search");
  const teamFilterEl = document.getElementById("events-team-filter");
  const searchText = searchEl?.value?.toLowerCase() || "";
  const teamFilter = teamFilterEl?.value || "";

  // Events arrive newest-first; reverse so newest is at the bottom (auto-scroll target)
  const events = getEvents().slice(0, 40).reverse();

  // Group events by pipeline stage for readability
  let html = "";
  let currentStage = null;

  for (const e of events) {
    // Apply filters
    if (searchText && !e.text.toLowerCase().includes(searchText)) continue;
    if (teamFilter && !_eventMatchesTeam(e, teamFilter)) continue;
    // Extract stage from event text or detect stage changes
    const stageMatch = e.text.match(/\u2192 (\w+)/);
    const eventStage = stageMatch ? stageMatch[1] : null;

    if (e.type === "pipeline_progress" && eventStage && eventStage !== currentStage) {
      currentStage = eventStage;
      const stageLabel = currentStage.replace(/_/g, " ").toUpperCase();
      html += `<div class="event-group__header">▸ ${stageLabel}</div>`;
    }

    // Extract agent name from event text for pill
    const agentMatch = e.text.match(/(?:agent_status|cost_update) ([a-z][\w-]+)/);
    const flowMatch = e.text.match(/message_flow ([a-z][\w-]+)\u2192([a-z][\w-]+)/);
    let agentPill = "";

    if (flowMatch) {
      const fromColor = getAgentTeamColor(flowMatch[1]);
      const toColor = getAgentTeamColor(flowMatch[2]);
      agentPill = `<span class="event__pill" style="background:${fromColor}20;color:${fromColor}">${flowMatch[1]}</span>` +
                  `<span class="event__arrow">→</span>` +
                  `<span class="event__pill" style="background:${toColor}20;color:${toColor}">${flowMatch[2]}</span>`;
    } else if (agentMatch) {
      const color = getAgentTeamColor(agentMatch[1]);
      agentPill = `<span class="event__pill" style="background:${color}20;color:${color}">${agentMatch[1]}</span>`;
    }

    const typeLabel = e.type.replace(/_/g, " ");
    html += `<div class="event event--${e.type}">` +
      `<span class="event__time">${e.time}</span>` +
      `<span class="event__type">${typeLabel}</span>` +
      (agentPill || `<span class="event__text">${escapeHtml(e.text)}</span>`) +
      `</div>`;
  }

  eventLogContainer.innerHTML = html;
  // Auto-scroll to show most recent entries at bottom
  eventLogContainer.scrollTop = eventLogContainer.scrollHeight;
}

function _eventMatchesTeam(event, teamFilter) {
  for (const agentName of (TEAMS[teamFilter]?.agents || [])) {
    if (event.text.includes(agentName)) return true;
  }
  return false;
}

function getAgentTeamColor(agentName) {
  const teamColors = {
    research: "#00d4ff", design: "#ff6ec7",
    commerce: "#39ff14", learning: "#ffae00",
    orchestrator: "#00d4ff",
  };
  for (const [teamId, team] of Object.entries(TEAMS)) {
    if (team.agents.includes(agentName)) return teamColors[teamId] || "#64748b";
  }
  return "#64748b";
}

// ---- Streaming typewriter state ----
let _lastCommCount = 0;       // detect new comms arriving
let _streamingTimer = null;   // active typing interval
let _streamingEl = null;      // DOM element being typed into
let _streamingWords = [];     // remaining words to type
let _streamingWordIdx = 0;

function _stopStreaming() {
  if (_streamingTimer) {
    clearInterval(_streamingTimer);
    _streamingTimer = null;
  }
  // Finalize any in-progress streaming element
  if (_streamingEl && _streamingWords.length > 0) {
    _streamingEl.textContent = _streamingWords.join(" ");
    _streamingEl.classList.remove("comm__body--streaming");
  }
  _streamingEl = null;
  _streamingWords = [];
  _streamingWordIdx = 0;
}

export function renderComms() {
  if (!commsFeedContainer) return;

  // Read log filter values
  const searchEl = document.getElementById("comms-search");
  const teamFilterEl = document.getElementById("comms-team-filter");
  const searchText = searchEl?.value?.toLowerCase() || "";
  const teamFilter = teamFilterEl?.value || "";

  // Reverse so newest entries appear at BOTTOM (natural scroll direction)
  const comms = getComms().slice(0, 40).reverse();
  const rawCount = getComms().length;
  const isNewComm = rawCount > _lastCommCount;
  _lastCommCount = rawCount;

  // Stop any active streaming before rebuilding DOM
  _stopStreaming();

  let html = "";

  for (let idx = 0; idx < comms.length; idx++) {
    const c = comms[idx];
    // Apply filters
    const commText = (c.content || "") + (c.agent || "") + (c.from || "") + (c.to || "");
    if (searchText && !commText.toLowerCase().includes(searchText)) continue;
    if (teamFilter) {
      const teamAgents = TEAMS[teamFilter]?.agents || [];
      const matchesTeam = teamAgents.some(a => commText.includes(a));
      if (!matchesTeam) continue;
    }
    const typeClass = c.type || "thinking";
    let header = "";
    let body = "";

    // Agent pill helper
    const agentPill = (name) => {
      const color = getAgentTeamColor(name);
      return `<span class="comm__pill" style="background:${color}20;color:${color};border:1px solid ${color}40">${escapeHtml(name)}</span>`;
    };

    const content = escapeHtml(c.content || "");
    // Newest entry (last after reverse) streams in; older long entries are collapsed
    const isNewest = idx === comms.length - 1 && isNewComm;
    const needsTruncation = idx < comms.length - 1 && content.length > 80;
    const truncated = content.length > 80 ? content.slice(0, 80) + "..." : content;

    if (c.type === "thinking") {
      const statusLabel = c.status === "active" ? "THINKING" : c.status === "idle" ? "DONE" : c.status?.toUpperCase() || "";
      header = `
        <span class="comm__badge comm__badge--thinking">${statusLabel}</span>
        ${agentPill(c.agent || "agent")}
        <span class="comm__time">${c.time}</span>`;
      if (isNewest && content.length > 20) {
        body = `<div class="comm__body comm__body--streaming" data-stream="${content}"></div>`;
      } else if (needsTruncation) {
        body = `<div class="comm__body comm__body--collapsed" data-full="${content}">${truncated}</div>`;
      } else {
        body = `<div class="comm__body">${content}</div>`;
      }
      if (c.decision) body += `<div class="comm__decision">⚡ ${escapeHtml(c.decision)}</div>`;
    } else if (c.type === "message") {
      header = `
        <span class="comm__badge comm__badge--message">MSG</span>
        ${agentPill(c.from || "?")} <span class="comm__arrow">→</span> ${agentPill(c.to || "?")}
        <span class="comm__time">${c.time}</span>`;
      if (isNewest && content.length > 20) {
        body = `<div class="comm__body comm__body--streaming" data-stream="${content}"></div>`;
      } else if (needsTruncation) {
        body = `<div class="comm__body comm__body--collapsed" data-full="${content}">${truncated}</div>`;
      } else {
        body = `<div class="comm__body">${content}</div>`;
      }
    } else if (c.type === "pipeline") {
      header = `
        <span class="comm__badge comm__badge--pipeline">STAGE</span>
        <span class="comm__agent">${escapeHtml((c.stage || "").replace(/_/g, " "))}</span>
        <span class="comm__time">${c.time}</span>`;
      body = `<div class="comm__body">${content}</div>`;
    } else if (c.type === "error") {
      header = `
        <span class="comm__badge comm__badge--error">ERR</span>
        ${agentPill(c.agent || "system")}
        <span class="comm__time">${c.time}</span>`;
      body = `<div class="comm__body">${content}</div>`;
    }

    html += `<div class="comm comm--${typeClass}${isNewest ? " comm--recent" : ""}"><div class="comm__header">${header}</div>${body}</div>`;
  }

  commsFeedContainer.innerHTML = html;

  // Start word-by-word streaming on the newest entry
  const streamEl = commsFeedContainer.querySelector(".comm__body--streaming");
  if (streamEl) {
    const fullText = streamEl.getAttribute("data-stream") || "";
    _streamingWords = fullText.split(/\s+/);
    _streamingWordIdx = 0;
    _streamingEl = streamEl;
    streamEl.textContent = "";
    // Type 3 words per tick, every 60ms = ~50 words/sec for a fluid streaming feel
    _streamingTimer = setInterval(() => {
      if (_streamingWordIdx >= _streamingWords.length) {
        clearInterval(_streamingTimer);
        _streamingTimer = null;
        streamEl.classList.remove("comm__body--streaming");
        // After streaming completes, collapse if long
        if (fullText.length > 80) {
          setTimeout(() => {
            if (streamEl.isConnected) {
              streamEl.textContent = fullText.slice(0, 80) + "...";
              streamEl.classList.add("comm__body--collapsed");
              streamEl.setAttribute("data-full", fullText);
              streamEl.style.cursor = "pointer";
              streamEl.title = "Click to expand";
            }
          }, 2000);
        }
        return;
      }
      const chunk = _streamingWords.slice(_streamingWordIdx, _streamingWordIdx + 2).join(" ");
      streamEl.textContent += (_streamingWordIdx > 0 ? " " : "") + chunk;
      _streamingWordIdx += 2;
      // Keep scrolled to bottom during streaming
      commsFeedContainer.scrollTop = commsFeedContainer.scrollHeight;
    }, 120);
  }

  // Click-to-expand collapsed messages
  commsFeedContainer.querySelectorAll(".comm__body--collapsed").forEach((el) => {
    el.style.cursor = "pointer";
    el.title = "Click to expand";
    el.addEventListener("click", () => {
      const full = el.getAttribute("data-full");
      if (full) {
        el.textContent = full;
        el.classList.remove("comm__body--collapsed");
        el.style.cursor = "";
        el.title = "";
      }
    });
  });

  // Auto-scroll to show most recent entries at bottom
  commsFeedContainer.scrollTop = commsFeedContainer.scrollHeight;
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function renderConnection(status) {
  if (connDot) connDot.className = "dot dot--" + (status === "connected" ? "green" : status === "connecting" ? "yellow" : "red");
  if (connText) connText.textContent = status;
}
