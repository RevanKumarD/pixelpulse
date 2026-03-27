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
  getFocusedRoom,
  setFocusedRoom,
  isRoomCollapsed,
  toggleRoomCollapsed,
  isTeamHidden,
  setHiddenTeams,
  getVisibleTeamIds,
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

// ---- Settings-controlled variables ----
let animSpeed = 1.0;
let fontScale = 1.0;    // 0.75 – 1.5, multiplied into every font size

/** Scale a font size by the user's fontScale setting. */
function fs(base) { return Math.round(base * fontScale); }

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
const ROOM_GAP = 3;          // tiles gap between rooms
const SITTING_OFFSET = 12;
const ORCH_ROWS = 2;         // orchestrator zone height in tiles (fits within gap)

// Content padding (tiles on each side of the room grid)
const PAD_TOP = 2;      // room labels above top rooms
const PAD_BOTTOM = 2;   // space below bottom rooms
const PAD_LEFT = 1;
const PAD_RIGHT = 2;    // agent name cards extend slightly beyond room edge

// ---- Dynamic Layout Engine ----
// Mutable layout state — recomputed by rebuildLayout()
let gridCols = 2;            // number of room columns
let gridRows = 2;            // number of room rows
let roomDims = {};            // { teamId: { cols, rows } }  per-room dimensions
let maxRoomCols = 9;          // widest room in grid (for column alignment)
let maxRoomRows = 9;          // tallest room in grid (for row alignment)
let CONTENT_TILES_W = 30;    // recomputed by rebuildLayout()
let CONTENT_TILES_H = 28;    // recomputed by rebuildLayout()
let layoutTeamOrder = [];     // ordered team IDs for grid placement

/**
 * Compute grid dimensions from team count.
 * Returns { cols, rows } where cols * rows >= teamCount.
 */
function computeGrid(teamCount) {
  if (teamCount <= 0) return { cols: 1, rows: 1 };
  const cols = Math.ceil(Math.sqrt(teamCount));
  const rows = Math.ceil(teamCount / cols);
  return { cols, rows };
}

/**
 * Compute room tile dimensions based on agent count and sizing mode.
 * Returns tile count (7, 9, 12, or 14).
 */
function computeRoomSize(agentCount, mode) {
  if (mode === 'compact') return 7;  // always small — overflow icons for extras
  if (agentCount <= 2) return 9;
  if (agentCount <= 4) return 12;
  if (agentCount <= 8) return 14;
  return 16;
}

/**
 * Determine team placement order.
 * Pipeline teams first (in pipeline order), then remaining teams.
 */
function computeTeamOrder(teams, pipelineStages, stageToTeam) {
  const order = [];
  const placed = new Set();

  // Pipeline teams in stage order
  if (pipelineStages && pipelineStages.length > 0) {
    for (const stage of pipelineStages) {
      const teamId = stageToTeam[stage];
      if (teamId && teams[teamId] && !placed.has(teamId)) {
        order.push(teamId);
        placed.add(teamId);
      }
    }
  }

  // Remaining teams in config order
  for (const teamId of Object.keys(teams)) {
    if (!placed.has(teamId)) {
      order.push(teamId);
      placed.add(teamId);
    }
  }

  return order;
}

/**
 * Full layout recomputation. Call when teams change or settings change.
 * Reads from TEAMS, PIPELINE_STAGES, STAGE_TO_TEAM (state.js imports)
 * and Settings for roomSizing mode.
 */
function rebuildLayout() {
  const teams = TEAMS;
  const allTeamIds = computeTeamOrder(teams, PIPELINE_STAGES, STAGE_TO_TEAM);
  // Filter out hidden teams (team filter)
  layoutTeamOrder = allTeamIds.filter(id => !isTeamHidden(id));

  const visibleCount = layoutTeamOrder.length || 1;
  const grid = computeGrid(visibleCount);
  gridCols = grid.cols;
  gridRows = grid.rows;

  const sizingMode = getSetting('roomSizing') || 'uniform';

  if (sizingMode === 'uniform') {
    // All rooms same size — based on team with most agents
    const maxAgents = Math.max(1, ...layoutTeamOrder.map(id => (teams[id]?.agents || []).length));
    const uniformSize = computeRoomSize(maxAgents, 'uniform');
    roomDims = {};
    for (const id of layoutTeamOrder) {
      roomDims[id] = { cols: uniformSize, rows: uniformSize };
    }
    maxRoomCols = uniformSize;
    maxRoomRows = uniformSize;
  } else {
    // Adaptive or compact — per-room sizing
    roomDims = {};
    let widest = 7, tallest = 7;
    for (const id of layoutTeamOrder) {
      const agentCount = (teams[id]?.agents || []).length;
      const size = computeRoomSize(agentCount, sizingMode);
      roomDims[id] = { cols: size, rows: size };
      if (size > widest) widest = size;
      if (size > tallest) tallest = size;
    }
    maxRoomCols = widest;
    maxRoomRows = tallest;
  }

  // Orchestrator zone height
  const orchHeight = getSetting('orchestratorVisible') !== false
    ? ORCH_ROWS + 1   // +1 gap tile
    : 0;

  // Content bounds
  CONTENT_TILES_W = PAD_LEFT + gridCols * maxRoomCols + (gridCols - 1) * ROOM_GAP + PAD_RIGHT;
  CONTENT_TILES_H = PAD_TOP + gridRows * maxRoomRows + (gridRows - 1) * ROOM_GAP + orchHeight + PAD_BOTTOM;
}

// Team colors for room walls/floors — floor colors closer together for softer tile pattern
const TEAM_STYLES = {
  research: { wall: "#105a74", floor1: "#0f2236", floor2: "#152d44", accent: "#00d4ff" },
  design:   { wall: "#551e4c", floor1: "#1e1028", floor2: "#281838", accent: "#ff6ec7" },
  commerce: { wall: "#1a5236", floor1: "#0f2216", floor2: "#162c1e", accent: "#39ff14" },
  learning: { wall: "#553f14", floor1: "#20180a", floor2: "#2a2010", accent: "#ffae00" },
};

// Color palette for dynamic team generation (teams not in TEAM_STYLES get a deterministic style)
// Floor colors kept close together for soft tile pattern; walls slightly brighter
const DYNAMIC_COLORS = [
  { wall: "#105a74", floor1: "#0f2236", floor2: "#152d44", accent: "#00d4ff" },
  { wall: "#551e4c", floor1: "#1e1028", floor2: "#281838", accent: "#ff6ec7" },
  { wall: "#1a5236", floor1: "#0f2216", floor2: "#162c1e", accent: "#39ff14" },
  { wall: "#553f14", floor1: "#20180a", floor2: "#2a2010", accent: "#ffae00" },
  { wall: "#351f55", floor1: "#161220", floor2: "#201a30", accent: "#aa88ff" },
  { wall: "#553314", floor1: "#201608", floor2: "#2a200e", accent: "#ff8844" },
  { wall: "#145555", floor1: "#0f2020", floor2: "#182a2a", accent: "#44ffdd" },
  { wall: "#551435", floor1: "#1e1018", floor2: "#281822", accent: "#ff44aa" },
  { wall: "#444414", floor1: "#1c1c0a", floor2: "#24240e", accent: "#dddd44" },
  { wall: "#143555", floor1: "#0f1620", floor2: "#18202a", accent: "#4488ff" },
];

/**
 * Get style for a team. Returns the hardcoded style if known,
 * otherwise generates a deterministic style from the teamId hash and caches it.
 */
function getTeamStyle(teamId) {
  if (TEAM_STYLES[teamId]) return TEAM_STYLES[teamId];

  // Generate deterministic style from team ID via djb2 hash
  let hash = 0;
  for (let i = 0; i < teamId.length; i++) {
    hash = ((hash << 5) - hash) + teamId.charCodeAt(i);
    hash |= 0;
  }
  const idx = Math.abs(hash) % DYNAMIC_COLORS.length;
  const style = DYNAMIC_COLORS[idx];

  // Cache it so repeated calls are O(1)
  TEAM_STYLES[teamId] = style;
  return style;
}

// ---- State ----
let canvas, ctx;
let zoom = 2;
let baseZoom = 2;     // auto-calculated to fit content
let userZoom = 1;     // user's manual zoom multiplier
let panX = 0, panY = 0;  // pan offset in pixels
let isPanning = false;
let panStartX = 0, panStartY = 0;
let panModeActive = false;  // toggled by Pan button — enables left-click drag panning
let tick = 0;
let hoveredAgent = null;
let mouseX = 0, mouseY = 0;

// Agent screen positions for particles & tooltips
const agentPositions = {}; // { agentName: { x, y, w, h } }

// Room label hit areas — updated each render() frame for click detection
// { teamId: { x, y, w, h } } in CSS pixels (not DPR-scaled)
const roomLabelRects = {};

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
  // Invalidate BFS walkable grid cache for this room
  delete _walkableGridCache[teamId];
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

// Room walls — per-room bounds derived from dynamic room dimensions
function getRoomBounds(teamId) {
  const dims = roomDims[teamId] || { cols: 9, rows: 9 };
  return {
    minCol: 1.2,
    maxCol: dims.cols - 1.8,
    minRow: 1.2,
    maxRow: dims.rows - 1.8,
  };
}

function _isInsideRoom(col, row, teamId) {
  const b = getRoomBounds(teamId);
  return col >= b.minCol && col <= b.maxCol &&
         row >= b.minRow && row <= b.maxRow;
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
  return _collidesWithFurniture(teamId, col, row) || !_isInsideRoom(col, row, teamId);
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
    if (_collidesWithFurniture(teamId, c, r) || !_isInsideRoom(c, r, teamId)) return false;
  }
  return true;
}

// BFS pathfinding — inspired by pablodelucca/pixel-agents tile-grid approach
// Cache walkable grids per room (furniture is static at runtime)
const _walkableGridCache = {};

function _buildWalkableGrid(teamId) {
  const dims = roomDims[teamId] || { cols: 9, rows: 9 };
  const bounds = getRoomBounds(teamId);
  const grid = [];
  for (let r = 0; r < dims.rows; r++) {
    const row = [];
    for (let c = 0; c < dims.cols; c++) {
      const tc = c + 0.5; // tile center in continuous tile coords
      const tr = r + 0.5;
      row.push(
        tc >= bounds.minCol && tc <= bounds.maxCol &&
        tr >= bounds.minRow && tr <= bounds.maxRow &&
        !_collidesWithFurniture(teamId, tc, tr)
      );
    }
    grid.push(row);
  }
  return grid;
}

function _getWalkableGrid(teamId) {
  if (!_walkableGridCache[teamId]) {
    _walkableGridCache[teamId] = _buildWalkableGrid(teamId);
  }
  return _walkableGridCache[teamId];
}

// 4-connected BFS from continuous position to continuous target.
// Returns array of { col, row } waypoints (tile centers + exact target at end).
// Returns [] if no path exists.
function _findPathBFS(fromCol, fromRow, toCol, toRow, teamId) {
  const dims = roomDims[teamId] || { cols: 9, rows: 9 };
  const grid = _getWalkableGrid(teamId);

  const startC = Math.max(0, Math.min(dims.cols - 1, Math.floor(fromCol)));
  const startR = Math.max(0, Math.min(dims.rows - 1, Math.floor(fromRow)));
  const endC   = Math.max(0, Math.min(dims.cols - 1, Math.floor(toCol)));
  const endR   = Math.max(0, Math.min(dims.rows - 1, Math.floor(toRow)));

  if (startC === endC && startR === endR) return [{ col: toCol, row: toRow }];

  const rows = dims.rows, cols = dims.cols;
  const visited = new Uint8Array(rows * cols);
  const parentC = new Int8Array(rows * cols).fill(-1);
  const parentR = new Int8Array(rows * cols).fill(-1);

  const idx = (c, r) => r * cols + c;
  const queue = [startC, startR]; // flat array for speed
  visited[idx(startC, startR)] = 1;
  const DIRS = [[0,-1],[0,1],[-1,0],[1,0]];
  let found = false;
  let qi = 0;

  outer: while (qi < queue.length) {
    const c = queue[qi++], r = queue[qi++];
    if (c === endC && r === endR) { found = true; break; }
    for (const [dc, dr] of DIRS) {
      const nc = c + dc, nr = r + dr;
      if (nc < 0 || nc >= cols || nr < 0 || nr >= rows) continue;
      const ni = idx(nc, nr);
      if (visited[ni] || !grid[nr][nc]) continue;
      visited[ni] = 1;
      parentC[ni] = c;
      parentR[ni] = r;
      queue.push(nc, nr);
    }
  }

  if (!found) return [];

  // Reconstruct path from end back to start
  const path = [];
  let c = endC, r = endR;
  while (!(c === startC && r === startR)) {
    path.push({ col: c + 0.5, row: r + 0.5 });
    const ni = idx(c, r);
    const pc = parentC[ni], pr = parentR[ni];
    c = pc; r = pr;
  }
  path.reverse();

  // Replace final waypoint with exact target position
  if (path.length > 0) path[path.length - 1] = { col: toCol, row: toRow };
  return path;
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
  const b = getRoomBounds(teamId);
  for (let attempt = 0; attempt < 15; attempt++) {
    const col = b.minCol + 0.5 + Math.random() * (b.maxCol - b.minCol - 1);
    const row = b.minRow + 0.5 + Math.random() * (b.maxRow - b.minRow - 1);
    if (!_collidesWithFurniture(teamId, col, row)) {
      return { col, row };
    }
  }
  // Fallback: center of room (always safe)
  const dims = roomDims[teamId] || { cols: 9, rows: 9 };
  return { col: dims.cols / 2, row: dims.rows / 2 };
}

function _buildWaypoints(rs) {
  // BFS pathfinding — finds obstacle-aware route through tile grid
  const target = _pickSafeTarget(rs.roomTeamId);
  rs.targetCol = target.col;
  rs.targetRow = target.row;

  const path = _findPathBFS(rs.col, rs.row, target.col, target.row, rs.roomTeamId);
  if (path.length > 0) {
    rs.waypoints = path;
  } else {
    // BFS found no path — fall back to direct (collision will slide around obstacles)
    rs.waypoints = [target];
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
        // BFS path back to desk when waypoints run out
        if (!rs.waypoints.length || rs.waypointIdx >= rs.waypoints.length) {
          const desk = { col: rs.deskCol, row: rs.deskRow };
          const path = _findPathBFS(rs.col, rs.row, desk.col, desk.row, rs.roomTeamId);
          rs.waypoints = path.length > 0 ? path : [desk];
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

        // Push both agents apart equally, respecting per-room walls & furniture
        const bA = getRoomBounds(rsA.roomTeamId);
        const bB = getRoomBounds(rsB.roomTeamId);
        const aCol = Math.max(bA.minCol, Math.min(rsA.col + pushX, bA.maxCol));
        const aRow = Math.max(bA.minRow, Math.min(rsA.row + pushY, bA.maxRow));
        const bCol = Math.max(bB.minCol, Math.min(rsB.col - pushX, bB.maxCol));
        const bRow = Math.max(bB.minRow, Math.min(rsB.row - pushY, bB.maxRow));

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
        if (!_collidesWithFurniture(rsA.roomTeamId, aCol, aRow) && _isInsideRoom(aCol, aRow, rsA.roomTeamId)) {
          rsA.col = aCol; rsA.row = aRow;
        }
      }
    }
  }
}

// ---- Sidebar DOM refs ----
let pipelineContainer, runsContainer, costContainer, eventLogContainer, commsFeedContainer, agentActivityContainer, connDot, connText;

// ---- Minimap ----
let minimapCanvas, minimapCtx;

function initMinimap() {
  minimapCanvas = document.getElementById("minimap-canvas");
  if (!minimapCanvas) return;
  minimapCtx = minimapCanvas.getContext("2d");

  // Click-to-pan: translate minimap click fraction to main canvas pan
  minimapCanvas.addEventListener("click", (e) => {
    if (!minimapCtx) return;
    const rect = minimapCanvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const mw = minimapCanvas.width;
    const mh = minimapCanvas.height;
    const fracX = mx / mw;
    const fracY = my / mh;

    const s = TILE_SIZE * zoom;
    const contentW = CONTENT_TILES_W * s;
    const contentH = CONTENT_TILES_H * s;
    const dpr = window.devicePixelRatio || 1;
    const cw = canvas.width;
    const ch = canvas.height;

    // Pan so the clicked content fraction is at canvas center
    panX = ((cw / 2) - (fracX * contentW + (cw - contentW) / 2)) / dpr;
    panY = ((ch / 2) - (fracY * contentH + (ch - contentH) / 2)) / dpr;
  });
}

function drawMinimap() {
  if (!minimapCanvas || !minimapCtx) return;
  const mw = minimapCanvas.width;
  const mh = minimapCanvas.height;
  const mc = minimapCtx;

  // Auto-hide when content fits viewport (no zoom or pan)
  const needsMinimap = userZoom !== 1 || panX !== 0 || panY !== 0;
  minimapCanvas.classList.toggle("minimap--hidden", !needsMinimap);
  if (!needsMinimap) return;

  mc.clearRect(0, 0, mw, mh);
  mc.fillStyle = "rgba(10,14,23,0.9)";
  mc.fillRect(0, 0, mw, mh);

  const dpr = window.devicePixelRatio || 1;
  const s = TILE_SIZE * zoom;
  const cw = canvas.width;
  const ch = canvas.height;
  const contentW = CONTENT_TILES_W * s;
  const contentH = CONTENT_TILES_H * s;

  const contentOffsetX = Math.floor((cw - contentW) / 2) + panX * dpr;
  const contentOffsetY = Math.floor((ch - contentH) / 2) + panY * dpr;
  const offsetX = contentOffsetX + PAD_LEFT * s;
  const offsetY = contentOffsetY + PAD_TOP * s;
  const orchOffset = (getSetting('orchestratorVisible') !== false && gridRows > 1)
    ? (ORCH_ROWS + 1) : 0;

  // Draw simplified room rects
  for (let i = 0; i < layoutTeamOrder.length; i++) {
    const teamId = layoutTeamOrder[i];
    const team = TEAMS[teamId];
    if (!team) continue;
    const roomCol = i % gridCols;
    const roomRow = Math.floor(i / gridCols);
    const dims = roomDims[teamId] || { cols: 9, rows: 9 };
    const rx = offsetX + roomCol * (maxRoomCols + ROOM_GAP) * s;
    let ry;
    if (roomRow === 0) {
      ry = offsetY;
    } else {
      ry = offsetY + maxRoomRows * s + orchOffset * s + (roomRow - 1) * (maxRoomRows + ROOM_GAP) * s;
    }

    // Project main-canvas pixels → minimap pixels
    const mmx = (rx / cw) * mw;
    const mmy = (ry / ch) * mh;
    const mmrw = (dims.cols * s / cw) * mw;
    const mmrh = (dims.rows * s / ch) * mh;

    const style = TEAM_STYLES[teamId] || TEAM_STYLES.research;
    const hex = style.accent.replace('#', '');
    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);

    mc.fillStyle = `rgba(${r},${g},${b},0.5)`;
    mc.fillRect(Math.round(mmx), Math.round(mmy), Math.max(2, Math.round(mmrw)), Math.max(2, Math.round(mmrh)));

    if (getFocusedRoom() === teamId) {
      mc.strokeStyle = style.accent;
      mc.lineWidth = 1.5;
      mc.strokeRect(Math.round(mmx), Math.round(mmy), Math.max(2, Math.round(mmrw)), Math.max(2, Math.round(mmrh)));
    }
  }

  // Viewport rectangle
  const vpLeft = -contentOffsetX;
  const vpTop = -contentOffsetY;
  const vmx = (vpLeft / contentW) * mw;
  const vmy = (vpTop / contentH) * mh;
  const vmw = (cw / contentW) * mw;
  const vmh = (ch / contentH) * mh;

  mc.strokeStyle = "rgba(255,255,255,0.8)";
  mc.lineWidth = 1;
  mc.strokeRect(Math.round(vmx), Math.round(vmy), Math.round(vmw), Math.round(vmh));

  // Label
  mc.fillStyle = "rgba(100,116,139,0.8)";
  mc.font = `7px "JetBrains Mono", monospace`;
  mc.textAlign = "left";
  mc.textBaseline = "top";
  mc.fillText("MAP", 3, 2);
}

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

  // Pan — middle-click, shift+click drag, or left-click when pan mode is active
  canvas.addEventListener("mousedown", (e) => {
    if (e.button === 1 || (e.button === 0 && e.shiftKey) || (e.button === 0 && panModeActive)) {
      isPanning = true;
      panStartX = e.clientX - panX;
      panStartY = e.clientY - panY;
      canvas.style.cursor = "grabbing";
      e.preventDefault();
    }
  });
  window.addEventListener("mousemove", (e) => {
    if (isPanning) {
      panX = e.clientX - panStartX;
      panY = e.clientY - panStartY;
    }
  });
  window.addEventListener("mouseup", () => {
    isPanning = false;
    canvas.style.cursor = panModeActive ? "grab" : "";
  });

  // Double-click: focus on room under cursor, or fit view if outside rooms or already focused
  canvas.addEventListener("dblclick", (e) => {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const cx = (e.clientX - rect.left) * dpr;
    const cy = (e.clientY - rect.top) * dpr;
    const hitTeam = hitTestRoom(cx, cy);
    if (hitTeam && getFocusedRoom() !== hitTeam) {
      zoomToRoom(hitTeam);
    } else {
      setFocusedRoom(null);
      fitView();
    }
  });

  // Click detection — room label collapse first, then agent click
  canvas.addEventListener("click", (e) => {
    if (e.shiftKey) return; // shift+click is pan, skip
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    // Check room label rects first (CSS pixels)
    for (const [teamId, labelRect] of Object.entries(roomLabelRects)) {
      if (mx >= labelRect.x && mx <= labelRect.x + labelRect.w &&
          my >= labelRect.y && my <= labelRect.y + labelRect.h) {
        toggleRoomCollapsed(teamId);
        return;
      }
    }
    // Agent click detection
    const cx = mx * dpr;
    const cy = my * dpr;
    for (const [name, pos] of Object.entries(agentPositions)) {
      if (cx >= pos.x && cx <= pos.x + pos.w && cy >= pos.y && cy <= pos.y + pos.h) {
        canvas.dispatchEvent(new CustomEvent("agent-click", { detail: { agentName: name } }));
        return;
      }
    }
  });

  // ---- Wire all settings ----
  animSpeed = getSetting("animationSpeed") ?? 1.0;
  onSettingChange("animationSpeed", (v) => { animSpeed = v; });

  fontScale = getSetting("fontScale") ?? 1.0;
  onSettingChange("fontScale", (v) => { fontScale = v; });

  // Build initial layout and subscribe to layout-affecting settings
  rebuildLayout();
  resize();
  onSettingChange("roomSizing", () => { rebuildLayout(); resize(); });
  onSettingChange("orchestratorVisible", () => { rebuildLayout(); resize(); });

  // Scanlines toggle
  const scanlinesEl = document.querySelector(".scanlines");
  if (scanlinesEl) {
    scanlinesEl.style.display = getSetting("scanlinesEnabled") ? "" : "none";
    onSettingChange("scanlinesEnabled", (v) => { scanlinesEl.style.display = v ? "" : "none"; });
  }

  // Canvas smoothing
  const applySmoothing = (v) => { ctx.imageSmoothingEnabled = !!v; };
  applySmoothing(getSetting("canvasSmoothing"));
  onSettingChange("canvasSmoothing", applySmoothing);

  // Zoom level from settings (initial + updates)
  const settingZoom = getSetting("zoomLevel");
  if (settingZoom != null) userZoom = settingZoom;
  onSettingChange("zoomLevel", (v) => { userZoom = v; zoom = baseZoom * userZoom; });

  // Sidebar visibility
  const sidebarEl = document.querySelector(".sidebar");
  if (sidebarEl) {
    if (!getSetting("sidebarVisible")) sidebarEl.classList.add("sidebar--hidden");
    onSettingChange("sidebarVisible", (v) => {
      sidebarEl.classList.toggle("sidebar--hidden", !v);
      requestAnimationFrame(() => resize());
    });
  }

  // Bottom bar height
  const root = document.documentElement;
  const applyBottomH = (v) => { root.style.setProperty("--bottom-h", v + "px"); requestAnimationFrame(() => resize()); };
  applyBottomH(getSetting("bottomBarHeight") ?? 220);
  onSettingChange("bottomBarHeight", applyBottomH);

  // Sidebar section toggles (pipeline, agents, runs, cost)
  for (const sectionKey of ["pipeline", "agents", "runs"]) {
    const section = document.querySelector(`[data-sidebar-section="${sectionKey}"]`);
    if (!section) continue;
    const settingKey = `sidebarSections.${sectionKey}`;
    const applyVis = (v) => { section.style.display = v === false ? "none" : ""; };
    applyVis(getSetting(settingKey));
    onSettingChange(settingKey, applyVis);
  }
  // Cost pill toggle
  const costPill = document.getElementById("cost-pill");
  if (costPill) {
    const applyCostVis = (v) => { costPill.style.display = v === false ? "none" : ""; };
    applyCostVis(getSetting("sidebarSections.cost"));
    onSettingChange("sidebarSections.cost", applyCostVis);
  }

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
  initTeamFilter();

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

  initMinimap();
  requestAnimationFrame(gameLoop);
}

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
  baseZoom = Math.max(0.25, Math.min(zoomW, zoomH));
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

/** Toggle pan mode — when active, left-click drag pans the canvas */
export function togglePanMode() {
  panModeActive = !panModeActive;
  const btn = document.getElementById("ctrl-pan");
  if (btn) btn.classList.toggle("canvas-ctrl--active", panModeActive);
  canvas.style.cursor = panModeActive ? "grab" : "";
  return panModeActive;
}

/** Pan camera to center on a team room */
export function panToTeam(teamId) {
  const idx = layoutTeamOrder.indexOf(teamId);
  if (idx === -1) return;
  const roomCol = idx % gridCols;
  const roomRow = Math.floor(idx / gridCols);
  const dims = roomDims[teamId] || { cols: 9, rows: 9 };
  const s = TILE_SIZE * zoom;

  const contentW = CONTENT_TILES_W * s;
  const contentH = CONTENT_TILES_H * s;
  const w = canvas.width;
  const h = canvas.height;
  const contentOffsetX = (w - contentW) / 2;
  const contentOffsetY = (h - contentH) / 2;
  const orchOffset = (getSetting('orchestratorVisible') !== false && gridRows > 1)
    ? (ORCH_ROWS + 1) : 0;
  const roomX = contentOffsetX + (PAD_LEFT + roomCol * (maxRoomCols + ROOM_GAP)) * s;
  let roomY;
  if (roomRow === 0) {
    roomY = contentOffsetY + PAD_TOP * s;
  } else {
    roomY = contentOffsetY + (PAD_TOP + maxRoomRows + orchOffset + (roomRow - 1) * (maxRoomRows + ROOM_GAP)) * s;
  }
  const roomCenterX = roomX + (dims.cols * s) / 2;
  const roomCenterY = roomY + (dims.rows * s) / 2;
  const dpr = window.devicePixelRatio || 1;

  userZoom = 1.5;
  zoom = baseZoom * userZoom;
  panX = (w / 2 - roomCenterX) / dpr;
  panY = (h / 2 - roomCenterY) / dpr;
}

/**
 * Compute the screen-space rectangle for a given team room.
 * Returns { rx, ry, rw, rh } in canvas pixels, or null if not found.
 */
function getRoomScreenRect(teamId) {
  const idx = layoutTeamOrder.indexOf(teamId);
  if (idx === -1) return null;
  const roomCol = idx % gridCols;
  const roomRow = Math.floor(idx / gridCols);
  const dims = roomDims[teamId] || { cols: 9, rows: 9 };
  const s = TILE_SIZE * zoom;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.width;
  const h = canvas.height;
  const contentW = CONTENT_TILES_W * s;
  const contentH = CONTENT_TILES_H * s;
  const contentOffsetX = Math.floor((w - contentW) / 2) + panX * dpr;
  const contentOffsetY = Math.floor((h - contentH) / 2) + panY * dpr;
  const offsetX = contentOffsetX + PAD_LEFT * s;
  const offsetY = contentOffsetY + PAD_TOP * s;
  const orchOffset = (getSetting('orchestratorVisible') !== false && gridRows > 1)
    ? (ORCH_ROWS + 1) : 0;
  const rx = offsetX + roomCol * (maxRoomCols + ROOM_GAP) * s;
  let ry;
  if (roomRow === 0) {
    ry = offsetY;
  } else {
    ry = offsetY + maxRoomRows * s
       + orchOffset * s
       + (roomRow - 1) * (maxRoomRows + ROOM_GAP) * s;
  }
  return { rx, ry, rw: dims.cols * s, rh: dims.rows * s };
}

/**
 * Hit-test a canvas-space point against all room rects.
 * Returns the teamId of the room under the point, or null.
 * Point (cx, cy) must be in canvas pixels (DPR-scaled).
 */
function hitTestRoom(cx, cy) {
  for (const teamId of layoutTeamOrder) {
    const rect = getRoomScreenRect(teamId);
    if (!rect) continue;
    if (cx >= rect.rx && cx <= rect.rx + rect.rw &&
        cy >= rect.ry && cy <= rect.ry + rect.rh) {
      return teamId;
    }
  }
  return null;
}

/**
 * Zoom in on a specific room, filling the viewport with it.
 * Sets focusedRoom state so render() draws the dim overlay.
 */
export function zoomToRoom(teamId) {
  if (!teamId || !layoutTeamOrder.includes(teamId)) return;
  setFocusedRoom(teamId);

  const idx = layoutTeamOrder.indexOf(teamId);
  const roomCol = idx % gridCols;
  const roomRow = Math.floor(idx / gridCols);
  const dims = roomDims[teamId] || { cols: 9, rows: 9 };

  // First fit view so we have a consistent base zoom
  const wrap = document.querySelector(".canvas-wrap");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.width;
  const h = canvas.height;

  // Compute zoom so the room fills ~80% of the viewport
  const roomPixW = dims.cols * TILE_SIZE;
  const roomPixH = dims.rows * TILE_SIZE;
  const marginX = 0.80, marginY = 0.80;
  const zoomW = (w * marginX) / (roomPixW * dpr);
  const zoomH = (h * marginY) / (roomPixH * dpr);
  const targetZoom = Math.min(zoomW, zoomH);

  // Reset base zoom to fit and set userZoom for the target
  const zoomFitW = w / (CONTENT_TILES_W * TILE_SIZE * dpr);
  const zoomFitH = h / (CONTENT_TILES_H * TILE_SIZE * dpr);
  baseZoom = Math.max(0.25, Math.min(zoomFitW, zoomFitH));
  userZoom = Math.max(0.5, Math.min(targetZoom / baseZoom, 3));
  zoom = baseZoom * userZoom;

  // Pan so the room is centered
  const s = TILE_SIZE * zoom;
  const contentW = CONTENT_TILES_W * s;
  const contentH = CONTENT_TILES_H * s;
  const contentOffsetX = (w - contentW) / 2;
  const contentOffsetY = (h - contentH) / 2;
  const offsetX = contentOffsetX + PAD_LEFT * s;
  const offsetY = contentOffsetY + PAD_TOP * s;
  const orchOffset = (getSetting('orchestratorVisible') !== false && gridRows > 1)
    ? (ORCH_ROWS + 1) : 0;
  const rx = offsetX + roomCol * (maxRoomCols + ROOM_GAP) * s;
  let ry;
  if (roomRow === 0) {
    ry = offsetY;
  } else {
    ry = offsetY + maxRoomRows * s
       + orchOffset * s
       + (roomRow - 1) * (maxRoomRows + ROOM_GAP) * s;
  }
  const roomCenterX = rx + (dims.cols * s) / 2;
  const roomCenterY = ry + (dims.rows * s) / 2;

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
  const totalW = (gridCols * maxRoomCols + (gridCols - 1) * ROOM_GAP) * s;

  // Orchestrator zone offset — pushes room rows 1+ down when visible
  const orchOffset = (getSetting('orchestratorVisible') !== false && gridRows > 1)
    ? (ORCH_ROWS + 1)  // orchestrator zone + gap tile
    : 0;

  // ---- Draw rooms ----
  const drawables = [];

  for (let i = 0; i < layoutTeamOrder.length; i++) {
    const teamId = layoutTeamOrder[i];
    const team = TEAMS[teamId];
    if (!team) continue;
    const roomCol = i % gridCols;
    const roomRow = Math.floor(i / gridCols);
    const dims = roomDims[teamId] || { cols: 9, rows: 9 };
    const rx = offsetX + roomCol * (maxRoomCols + ROOM_GAP) * s;
    let ry;
    if (roomRow === 0) {
      ry = offsetY;
    } else {
      ry = offsetY + maxRoomRows * s                        // first row height
         + orchOffset * s                                    // orchestrator zone
         + (roomRow - 1) * (maxRoomRows + ROOM_GAP) * s;   // subsequent rows
    }

    if (isRoomCollapsed(teamId)) {
      // Draw compact badge instead of full room
      drawCollapsedBadge(rx, ry, teamId, team);
    } else {
      drawRoom(rx, ry, teamId, dims.cols, dims.rows);
      drawRoomLabel(rx, ry, team, teamId, dims.cols);

      // Build drawables for z-sorting
      const items = buildRoomLayout(team, teamId, dims.cols, dims.rows);
      for (const item of items) {
        const ix = rx + item.col * s;
        const iy = ry + item.row * s;
        // No z-bonus: natural Y-order means desk/monitor draw ON TOP of agent
        const zY = iy;
        drawables.push({ type: item.type, x: ix, y: iy, zY, teamId, agent: item.agent, roaming: item.roaming, count: item.count });
      }
    }
  }

  // ---- Flow connectors overlay ----
  if (getSetting('showConnectors')) {
    drawFlowConnectors(offsetX, offsetY, s, orchOffset);
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
      case "overflow-agent": {
        // Small 8x8 pixel head icon for agents that didn't get a desk in compact mode
        const ovAgent = getAgent(d.agent);
        const ovStyle = getTeamStyle(d.teamId);
        const iconSize = 8 * zoom;
        const isActive = ovAgent?.status === "active";

        // Glow if active
        if (isActive) {
          ctx.save();
          ctx.shadowColor = ovStyle.accent;
          ctx.shadowBlur = 6 * zoom;
          ctx.fillStyle = ovStyle.accent;
          ctx.beginPath();
          ctx.arc(d.x + iconSize / 2, d.y + iconSize / 2, iconSize / 2, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        }
        // Head circle
        ctx.fillStyle = isActive ? ovStyle.accent : "#475569";
        ctx.beginPath();
        ctx.arc(d.x + iconSize / 2, d.y + iconSize / 2, iconSize / 2, 0, Math.PI * 2);
        ctx.fill();
        break;
      }
      case "overflow-badge": {
        const fontSize = fs(Math.max(8, Math.round(9 * zoom * 0.55)));
        ctx.save();
        ctx.font = `600 ${fontSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
        ctx.fillStyle = "#94a3b8";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(`+${d.count}`, d.x, d.y + 4 * zoom);
        ctx.restore();
        break;
      }
    }
  }

  // ---- Focus mode dim overlay ----
  const focusedTeam = getFocusedRoom();
  if (focusedTeam) {
    drawFocusOverlay(focusedTeam, offsetX, offsetY, s, orchOffset);
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
    ctx.font = '12px system-ui, -apple-system, "Segoe UI", sans-serif';
    ctx.fillStyle = "#475569";
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.fillText(`${Math.round(userZoom * 100)}% · dbl-click room to focus · 0/ESC to fit`, 12, h - 8);
    ctx.restore();
  } else {
    ctx.save();
    ctx.font = '11px system-ui, -apple-system, "Segoe UI", sans-serif';
    ctx.fillStyle = "#334155";
    ctx.textAlign = "left";
    ctx.textBaseline = "bottom";
    ctx.fillText("scroll to zoom · shift-drag to pan · dbl-click room to focus", 12, h - 8);
    ctx.restore();
  }

  // ---- Minimap ----
  drawMinimap();
}

// ---- Room Rendering ----

function drawRoom(rx, ry, teamId, roomCols, roomRows) {
  const s = TILE_SIZE * zoom;
  const style = getTeamStyle(teamId) || TEAM_STYLES.research;

  // ── Floor: base fill + SOFT alternating tile shimmer ──────
  // Blend floor1 and floor2 closer together for a softer checkerboard
  ctx.fillStyle = style.floor1;
  ctx.fillRect(rx, ry, roomCols * s, roomRows * s);

  ctx.globalAlpha = 0.5;  // softer tile contrast (was 1.0)
  ctx.fillStyle = style.floor2;
  for (let r = 0; r < roomRows; r++) {
    for (let c = 0; c < roomCols; c++) {
      if ((r + c) % 2 === 0) {
        ctx.fillRect(rx + c * s, ry + r * s, s, s);
      }
    }
  }
  ctx.globalAlpha = 1;

  // Grout lines: softer, thinner grid
  ctx.save();
  ctx.strokeStyle = "rgba(0,0,0,0.15)";  // was 0.3
  ctx.lineWidth = 0.5;  // was 1
  ctx.beginPath();
  for (let c = 1; c < roomCols; c++) {
    const lx = Math.round(rx + c * s) + 0.5;
    ctx.moveTo(lx, ry);
    ctx.lineTo(lx, ry + roomRows * s);
  }
  for (let r = 1; r < roomRows; r++) {
    const ly = Math.round(ry + r * s) + 0.5;
    ctx.moveTo(rx, ly);
    ctx.lineTo(rx + roomCols * s, ly);
  }
  ctx.stroke();
  ctx.restore();

  // ── Center carpet/rug — warm tinted area to break up tiles ──
  {
    const inset = Math.max(1.5, roomCols * 0.18);
    const carpetX = rx + inset * s;
    const carpetY = ry + inset * s;
    const carpetW = (roomCols - inset * 2) * s;
    const carpetH = (roomRows - inset * 2) * s;
    const hex = style.accent;
    const cr = parseInt(hex.slice(1, 3), 16);
    const cg = parseInt(hex.slice(3, 5), 16);
    const cb = parseInt(hex.slice(5, 7), 16);
    ctx.save();
    ctx.globalAlpha = 0.06;
    ctx.fillStyle = `rgb(${cr},${cg},${cb})`;
    ctx.beginPath();
    ctx.roundRect(carpetX, carpetY, carpetW, carpetH, s * 0.3);
    ctx.fill();
    // Carpet border — subtle accent outline
    ctx.globalAlpha = 0.12;
    ctx.strokeStyle = `rgb(${cr},${cg},${cb})`;
    ctx.lineWidth = Math.max(1, zoom * 0.8);
    ctx.stroke();
    ctx.restore();
  }

  // ── Overhead ceiling lights — warm white pools ──────────────
  // 2–3 light sources depending on room size, simulating fluorescent panels
  {
    const hex = style.accent;
    const lr = parseInt(hex.slice(1, 3), 16);
    const lg = parseInt(hex.slice(3, 5), 16);
    const lb = parseInt(hex.slice(5, 7), 16);
    // Blend accent with warm white (200,190,170) for natural office light
    const wr = Math.round(lr * 0.3 + 200 * 0.7);
    const wg = Math.round(lg * 0.3 + 190 * 0.7);
    const wb = Math.round(lb * 0.3 + 170 * 0.7);
    const lightRadius = Math.min(roomCols, roomRows) * s * 0.45;

    // Primary center light
    const cx0 = rx + (roomCols * s) / 2;
    const cy0 = ry + (roomRows * s) / 2;
    const grad0 = ctx.createRadialGradient(cx0, cy0, 0, cx0, cy0, lightRadius);
    grad0.addColorStop(0, `rgba(${wr},${wg},${wb},0.10)`);
    grad0.addColorStop(0.5, `rgba(${wr},${wg},${wb},0.04)`);
    grad0.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = grad0;
    ctx.fillRect(rx, ry, roomCols * s, roomRows * s);

    // Secondary lights at 1/3 and 2/3 horizontal (for rooms >= 9 tiles)
    if (roomCols >= 9) {
      const lightY = ry + roomRows * s * 0.4;
      for (const frac of [0.3, 0.7]) {
        const lx = rx + roomCols * s * frac;
        const grad = ctx.createRadialGradient(lx, lightY, 0, lx, lightY, lightRadius * 0.65);
        grad.addColorStop(0, `rgba(${wr},${wg},${wb},0.07)`);
        grad.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = grad;
        ctx.fillRect(rx, ry, roomCols * s, roomRows * s);
      }
    }

    // Accent-colored ambient (kept from original but boosted slightly)
    const ambGrad = ctx.createRadialGradient(cx0, cy0, 0, cx0, cy0, lightRadius * 1.3);
    ambGrad.addColorStop(0, `rgba(${lr},${lg},${lb},0.08)`);
    ambGrad.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = ambGrad;
    ctx.fillRect(rx, ry, roomCols * s, roomRows * s);
  }

  // ── Corner vignette — darken edges for depth ──────────────
  {
    const vigRadius = Math.max(roomCols, roomRows) * s * 0.8;
    const cx = rx + (roomCols * s) / 2;
    const cy = ry + (roomRows * s) / 2;
    const vigGrad = ctx.createRadialGradient(cx, cy, vigRadius * 0.5, cx, cy, vigRadius);
    vigGrad.addColorStop(0, "rgba(0,0,0,0)");
    vigGrad.addColorStop(1, "rgba(0,0,0,0.12)");
    ctx.fillStyle = vigGrad;
    ctx.fillRect(rx, ry, roomCols * s, roomRows * s);
  }

  // ── Walls ────────────────────────────────────────────────────
  const wallW = Math.max(3, zoom * 4);
  ctx.fillStyle = style.wall;
  ctx.fillRect(rx, ry, roomCols * s, wallW);                          // top
  ctx.fillRect(rx, ry, wallW, roomRows * s);                           // left
  ctx.fillRect(rx + roomCols * s - wallW, ry, wallW, roomRows * s);   // right
  ctx.fillRect(rx, ry + roomRows * s - wallW, roomCols * s, wallW);   // bottom

  // Inner wall shadow — softer, more natural
  ctx.save();
  const shadowW = Math.max(4, zoom * 5);
  const shadowGradT = ctx.createLinearGradient(rx, ry + wallW, rx, ry + wallW + shadowW);
  shadowGradT.addColorStop(0, "rgba(0,0,0,0.18)");  // was 0.25
  shadowGradT.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = shadowGradT;
  ctx.fillRect(rx + wallW, ry + wallW, roomCols * s - wallW * 2, shadowW);

  const shadowGradL = ctx.createLinearGradient(rx + wallW, ry, rx + wallW + shadowW, ry);
  shadowGradL.addColorStop(0, "rgba(0,0,0,0.12)");  // was 0.2
  shadowGradL.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = shadowGradL;
  ctx.fillRect(rx + wallW, ry, shadowW, roomRows * s);

  const shadowGradR = ctx.createLinearGradient(rx + roomCols * s - wallW, ry, rx + roomCols * s - wallW - shadowW, ry);
  shadowGradR.addColorStop(0, "rgba(0,0,0,0.12)");  // was 0.2
  shadowGradR.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = shadowGradR;
  ctx.fillRect(rx + roomCols * s - wallW - shadowW, ry, shadowW, roomRows * s);
  ctx.restore();

  // Accent highlight on top wall edge — brighter neon strip
  ctx.fillStyle = style.accent;
  ctx.globalAlpha = 0.65;  // was 0.55
  ctx.fillRect(rx, ry, roomCols * s, Math.max(2, zoom * 2.5));
  ctx.globalAlpha = 1;

  // Baseboard: brighter accent strips on all 4 walls
  {
    const baseH = Math.max(2, zoom * 2);  // was 1.5
    ctx.fillStyle = style.accent;
    ctx.globalAlpha = 0.28;  // was 0.18

    // Bottom baseboard
    ctx.fillRect(rx + wallW, ry + roomRows * s - wallW - baseH, roomCols * s - wallW * 2, baseH);
    // Left baseboard
    ctx.fillRect(rx + wallW, ry + wallW, baseH, roomRows * s - wallW * 2);
    // Right baseboard
    ctx.fillRect(rx + roomCols * s - wallW - baseH, ry + wallW, baseH, roomRows * s - wallW * 2);

    ctx.globalAlpha = 1;
  }

  // ── Wall light fixtures — small glowing dots on top wall ──
  {
    const hex = style.accent;
    const flr = parseInt(hex.slice(1, 3), 16);
    const flg = parseInt(hex.slice(3, 5), 16);
    const flb = parseInt(hex.slice(5, 7), 16);
    const fixtureCount = roomCols >= 12 ? 3 : 2;
    const fixtureSpacing = roomCols * s / (fixtureCount + 1);

    for (let fi = 1; fi <= fixtureCount; fi++) {
      const fx = rx + fi * fixtureSpacing;
      const fy = ry + wallW + zoom * 2;
      const fr = Math.max(2, zoom * 2.5);

      // Glow halo
      const fGrad = ctx.createRadialGradient(fx, fy, 0, fx, fy, fr * 4);
      fGrad.addColorStop(0, `rgba(${flr},${flg},${flb},0.15)`);
      fGrad.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = fGrad;
      ctx.fillRect(fx - fr * 4, fy - fr * 4, fr * 8, fr * 8);

      // Fixture dot
      ctx.fillStyle = `rgba(${Math.min(255, flr + 60)},${Math.min(255, flg + 60)},${Math.min(255, flb + 60)},0.9)`;
      ctx.beginPath();
      ctx.arc(fx, fy, fr, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // ── Active stage highlight ───────────────────────────────────
  const pipeline = getPipeline();
  const activeTeam = STAGE_TO_TEAM[pipeline.stage];
  if (activeTeam === teamId) {
    ctx.save();
    ctx.globalAlpha = 0.04 + 0.02 * Math.sin(tick * 0.05);
    ctx.fillStyle = style.accent;
    ctx.fillRect(rx, ry, roomCols * s, roomRows * s);
    ctx.restore();
  }
}

function drawRoomLabel(rx, ry, team, teamId, roomCols) {
  const s = TILE_SIZE * zoom;
  const dpr = window.devicePixelRatio || 1;
  const style = getTeamStyle(teamId);

  // Count active agents in this team
  const agentStates = team.agents.map(n => getAgent(n)).filter(Boolean);
  const activeCount = agentStates.filter(a => a.status === "active").length;
  const totalCount = agentStates.length;

  // Department name — readable but compact
  const nameSize = fs(Math.max(11, Math.round(12 * zoom * 0.65)));
  ctx.save();
  ctx.font = `700 ${nameSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";

  const cx = rx + (roomCols * s) / 2;
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
  const badgeSize = fs(Math.max(8, Math.round(9 * zoom * 0.55)));
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
  const roleSize = fs(Math.max(8, Math.round(9 * zoom * 0.5)));
  ctx.font = `${roleSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.textAlign = "center";
  ctx.fillStyle = "#64748b";
  ctx.globalAlpha = 0.8;
  ctx.fillText(team.role, cx, cy + nameSize * 0.8);

  ctx.restore();

  // Record label pill hit rect for click-to-collapse (CSS pixels)
  roomLabelRects[teamId] = {
    x: (cx - rw / 2) / dpr,
    y: (cy - rh / 2) / dpr,
    w: rw / dpr,
    h: rh / dpr,
  };
}

// ---- Flow Connectors Overlay ----

function drawFlowConnectors(offsetX, offsetY, s, orchOffset) {
  const pipelineTeams = [];
  const seen = new Set();
  for (const stage of PIPELINE_STAGES) {
    const teamId = STAGE_TO_TEAM[stage];
    if (teamId && TEAMS[teamId] && !seen.has(teamId)) {
      pipelineTeams.push(teamId);
      seen.add(teamId);
    }
  }
  if (pipelineTeams.length < 2) return;

  ctx.save();
  ctx.setLineDash([Math.max(4, zoom * 3), Math.max(3, zoom * 2)]);
  ctx.lineWidth = Math.max(1.5, zoom * 0.8);

  for (let i = 0; i < pipelineTeams.length - 1; i++) {
    const fromId = pipelineTeams[i];
    const toId = pipelineTeams[i + 1];
    const fromCenter = _getRoomCenter(fromId, offsetX, offsetY, s, orchOffset);
    const toCenter = _getRoomCenter(toId, offsetX, offsetY, s, orchOffset);
    if (!fromCenter || !toCenter) continue;

    const style = TEAM_STYLES[fromId] || TEAM_STYLES.research;
    const hex = style.accent.replace('#', '');
    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);
    ctx.strokeStyle = `rgba(${r},${g},${b},0.55)`;
    ctx.globalAlpha = 1;

    const sameRow = Math.abs(fromCenter.cy - toCenter.cy) < s * 2;
    ctx.beginPath();
    ctx.moveTo(fromCenter.cx, fromCenter.cy);
    if (sameRow) {
      ctx.lineTo(toCenter.cx, toCenter.cy);
    } else {
      const midX = (fromCenter.cx + toCenter.cx) / 2;
      ctx.lineTo(midX, fromCenter.cy);
      ctx.lineTo(midX, toCenter.cy);
      ctx.lineTo(toCenter.cx, toCenter.cy);
    }
    ctx.stroke();

    // Arrow head at destination
    const endAngle = sameRow
      ? Math.atan2(toCenter.cy - fromCenter.cy, toCenter.cx - fromCenter.cx)
      : Math.atan2(toCenter.cy - fromCenter.cy, 0);
    const arrowLen = Math.max(8, zoom * 4);
    ctx.globalAlpha = 0.75;
    ctx.lineWidth = Math.max(1.5, zoom * 0.9);
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(toCenter.cx, toCenter.cy);
    ctx.lineTo(toCenter.cx - arrowLen * Math.cos(endAngle - Math.PI / 6), toCenter.cy - arrowLen * Math.sin(endAngle - Math.PI / 6));
    ctx.moveTo(toCenter.cx, toCenter.cy);
    ctx.lineTo(toCenter.cx - arrowLen * Math.cos(endAngle + Math.PI / 6), toCenter.cy - arrowLen * Math.sin(endAngle + Math.PI / 6));
    ctx.stroke();
    ctx.lineWidth = Math.max(1.5, zoom * 0.8);
    ctx.setLineDash([Math.max(4, zoom * 3), Math.max(3, zoom * 2)]);
    ctx.globalAlpha = 1;
  }

  ctx.setLineDash([]);
  ctx.restore();
}

function _getRoomCenter(teamId, offsetX, offsetY, s, orchOffset) {
  const idx = layoutTeamOrder.indexOf(teamId);
  if (idx === -1) return null;
  const roomCol = idx % gridCols;
  const roomRow = Math.floor(idx / gridCols);
  const dims = roomDims[teamId] || { cols: 9, rows: 9 };
  const rx = offsetX + roomCol * (maxRoomCols + ROOM_GAP) * s;
  let ry;
  if (roomRow === 0) {
    ry = offsetY;
  } else {
    ry = offsetY + maxRoomRows * s + orchOffset * s + (roomRow - 1) * (maxRoomRows + ROOM_GAP) * s;
  }
  return { cx: rx + dims.cols * s / 2, cy: ry + dims.rows * s / 2 };
}

// ---- Focus Mode Overlay ----

function drawFocusOverlay(focusedTeamId, offsetX, offsetY, s, orchOffset) {
  const w = canvas.width;
  const h = canvas.height;

  const idx = layoutTeamOrder.indexOf(focusedTeamId);
  if (idx === -1) return;
  const roomCol = idx % gridCols;
  const roomRow = Math.floor(idx / gridCols);
  const dims = roomDims[focusedTeamId] || { cols: 9, rows: 9 };

  const rx = offsetX + roomCol * (maxRoomCols + ROOM_GAP) * s;
  let ry;
  if (roomRow === 0) {
    ry = offsetY;
  } else {
    ry = offsetY + maxRoomRows * s
       + orchOffset * s
       + (roomRow - 1) * (maxRoomRows + ROOM_GAP) * s;
  }

  const pad = s * 0.5;

  // Dim everything EXCEPT the focused room using an evenodd clip.
  // destination-out would erase room pixels from the canvas buffer —
  // evenodd clip leaves the room untouched while dimming everything else.
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, w, h);
  ctx.rect(rx - pad, ry - pad, dims.cols * s + pad * 2, dims.rows * s + pad * 2);
  ctx.clip("evenodd");
  ctx.globalAlpha = 0.75;
  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, w, h);
  ctx.restore();

  // Accent border around focused room
  const style = getTeamStyle(focusedTeamId) || TEAM_STYLES.research;
  ctx.save();
  ctx.strokeStyle = style.accent;
  ctx.lineWidth = Math.max(2, zoom * 1.5);
  ctx.globalAlpha = 0.8 + 0.2 * Math.sin(tick * 0.07);
  ctx.shadowColor = style.accent;
  ctx.shadowBlur = 12;
  ctx.strokeRect(rx - pad * 0.5, ry - pad * 0.5, dims.cols * s + pad, dims.rows * s + pad);
  ctx.restore();

  // Hint text: "ESC or 0 to return"
  ctx.save();
  const hintSize = fs(Math.max(9, Math.round(zoom * 3.5)));
  ctx.font = `${hintSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillStyle = "#94a3b8";
  ctx.globalAlpha = 0.7;
  ctx.fillText("ESC or 0 to return to overview", w / 2, 8);
  ctx.restore();
}

// ---- Collapsed Room Badge ----

function drawCollapsedBadge(rx, ry, teamId, team) {
  const s = TILE_SIZE * zoom;
  const dpr = window.devicePixelRatio || 1;
  const style = getTeamStyle(teamId) || TEAM_STYLES.research;

  // Badge: 3 tiles wide × 1 tile tall
  const bw = 3 * s;
  const bh = s;

  // Background
  ctx.save();
  ctx.globalAlpha = 0.9;
  ctx.fillStyle = "#0a0e17";
  ctx.beginPath();
  ctx.roundRect(rx, ry, bw, bh, s * 0.15);
  ctx.fill();

  // Accent border
  ctx.strokeStyle = style.accent;
  ctx.lineWidth = Math.max(1.5, zoom * 0.8);
  ctx.globalAlpha = 0.8;
  ctx.stroke();

  // Team icon (first char of label)
  const iconSize = Math.max(10, Math.round(s * 0.38));
  ctx.font = `700 ${iconSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.globalAlpha = 1;
  ctx.fillStyle = style.accent;
  ctx.fillText(team.icon || team.label[0], rx + s * 0.15, ry + bh / 2);

  // Team name
  const nameSize = Math.max(9, Math.round(s * 0.32));
  ctx.font = `700 ${nameSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.fillStyle = style.accent;
  ctx.fillText(team.label.toUpperCase().slice(0, 6), rx + s * 0.45, ry + bh / 2);

  // Agent count badge
  const agentStates = team.agents.map(n => getAgent(n)).filter(Boolean);
  const activeCount = agentStates.filter(a => a.status === "active").length;
  const countText = `${activeCount}/${team.agents.length}`;
  const countSize = Math.max(8, Math.round(s * 0.28));
  ctx.font = `600 ${countSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.textAlign = "right";
  ctx.fillStyle = activeCount > 0 ? style.accent : "#475569";
  ctx.fillText(countText, rx + bw - s * 0.35, ry + bh / 2);

  // Pulsing dot if active
  if (activeCount > 0) {
    const dotR = Math.max(2, zoom * 0.7);
    ctx.fillStyle = style.accent;
    ctx.globalAlpha = 0.7 + 0.3 * Math.sin(tick * 0.12);
    ctx.shadowColor = style.accent;
    ctx.shadowBlur = 5;
    ctx.beginPath();
    ctx.arc(rx + bw - s * 0.15, ry + bh / 2, dotR, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  ctx.restore();

  // Store label rect for click detection (CSS pixels)
  roomLabelRects[teamId] = {
    x: rx / dpr,
    y: ry / dpr,
    w: bw / dpr,
    h: bh / dpr,
  };
}

// ---- Orchestrator Zone ----

function drawOrchestratorZone(offsetX, offsetY, totalW, s) {
  if (getSetting('orchestratorVisible') === false) return;

  const orch = getOrchestrator();
  const pipeline = getPipeline();

  // Zone position: below the first row of rooms, uses ORCH_ROWS height
  const zy = offsetY + maxRoomRows * s + s * 0.5;  // half tile gap
  const zx = offsetX;
  const zw = totalW;
  const zh = ORCH_ROWS * s;
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
  const titleSize = fs(Math.max(10, Math.round(11 * zoom * 0.55)));
  ctx.font = `700 ${titleSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
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
  const labelSize = fs(Math.max(8, Math.round(9 * zoom * 0.5)));
  ctx.textBaseline = "top";
  ctx.font = `600 ${labelSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;

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
    const msgSize = fs(Math.max(8, Math.round(9 * zoom * 0.5)));
    ctx.font = `${msgSize}px "JetBrains Mono", monospace`;
    ctx.fillStyle = "#64748b";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(orch.message.slice(0, 80), cx, zy + zh * 0.85);
  }

  ctx.restore();
}

// ---- Room Layout ----

function buildRoomLayout(team, teamId, roomCols, roomRows) {
  const allAgents = team.agents;
  const items = [];
  const sizingMode = getSetting('roomSizing') || 'uniform';

  // In compact mode, max 6 agents get full desk treatment; rest become overflow icons
  const maxFullDesks = sizingMode === 'compact' ? 6 : allAgents.length;

  // Sort so active agents get priority for desk positions in compact mode
  let deskAgents, overflowAgents;
  if (sizingMode === 'compact' && allAgents.length > maxFullDesks) {
    const sorted = [...allAgents].sort((a, b) => {
      const aAgent = getAgent(a);
      const bAgent = getAgent(b);
      const aActive = aAgent?.status === "active" ? 0 : 1;
      const bActive = bAgent?.status === "active" ? 0 : 1;
      return aActive - bActive;
    });
    deskAgents = sorted.slice(0, maxFullDesks);
    overflowAgents = sorted.slice(maxFullDesks);
  } else {
    deskAgents = allAgents;
    overflowAgents = [];
  }

  // Adaptive centering: compute grid dimensions then center in room
  const cols = Math.min(deskAgents.length, 2);       // max 2 per row
  const rows = Math.ceil(deskAgents.length / 2);
  const deskSpacingX = 4;                            // cols between desks
  const deskSpacingY = 2.4;                          // rows between desks
  const agentOffset = 1.9;                           // agent sits behind monitor (sweet spot)
  const gridW = cols > 1 ? deskSpacingX : 0;         // total width of desk cluster
  const gridH = (rows - 1) * deskSpacingY + agentOffset; // include agent above top desk
  const startCol = (roomCols - gridW - 2) / 2;       // center horizontally (-2 for desk width)
  const startRow = (roomRows - gridH - 1) / 2 + agentOffset; // center the full unit, desk anchor

  for (let i = 0; i < deskAgents.length; i++) {
    const col = startCol + (i % 2) * deskSpacingX;
    const row = startRow + Math.floor(i / 2) * deskSpacingY;
    // Agent centered with monitor on desk, facing viewer
    const deskCenterCol = col + 0.4;  // monitor col = desk center reference
    const agentDeskRow = row - agentOffset;

    // Register desk position for roaming system
    initRoam(deskAgents[i], deskCenterCol, agentDeskRow, teamId);

    // Use roaming position for idle agents
    const agent = getAgent(deskAgents[i]);
    const rs = roamState[deskAgents[i]];
    const isRoaming = rs && agent?.status === "idle" && rs.state !== "seated";
    const agentCol = isRoaming ? rs.col : deskCenterCol;
    const agentRow = isRoaming ? rs.row : agentDeskRow;

    items.push({ type: "agent", col: agentCol, row: agentRow, agent: deskAgents[i], roaming: isRoaming });
    items.push({ type: "monitor", col: deskCenterCol, row: row - 0.15 });
    items.push({ type: "desk", col, row });
  }

  // Overflow agents: small head icons along bottom edge (compact mode only)
  if (overflowAgents.length > 0) {
    const iconSpacing = 1.2;
    const totalIconW = overflowAgents.length * iconSpacing;
    const startX = (roomCols - totalIconW) / 2;
    const iconY = roomRows - 1.0;

    for (let i = 0; i < overflowAgents.length; i++) {
      items.push({
        type: "overflow-agent",
        col: startX + i * iconSpacing,
        row: iconY,
        agent: overflowAgents[i],
        roaming: false,
      });
    }

    // +N badge after the icons
    items.push({
      type: "overflow-badge",
      col: startX + overflowAgents.length * iconSpacing,
      row: iconY,
      count: overflowAgents.length,
    });
  }

  // Decorations — scale with room size, spread to corners and walls
  const teamDecor = {
    research:  "whiteboard",
    design:    "easel",
    commerce:  "box",
    learning:  "trophy",
  };
  const FALLBACK_DECORS = ["whiteboard", "easel", "box", "trophy", "plant"];
  let _teamHash = 0;
  for (let _i = 0; _i < teamId.length; _i++) {
    _teamHash = ((_teamHash << 5) - _teamHash) + teamId.charCodeAt(_i);
    _teamHash |= 0;
  }
  const decor = teamDecor[teamId] || FALLBACK_DECORS[Math.abs(_teamHash) % FALLBACK_DECORS.length];

  // Core furniture — always present (3 items)
  items.push({ type: "plant", col: 0.5, row: 0.5 });                     // top-left
  items.push({ type: decor, col: roomCols - 1.5, row: 0.5 });            // top-right
  items.push({ type: "bookshelf", col: 0.5, row: roomRows - 2.25 });     // bottom-left

  // Standard rooms (9+): add bottom-right plant and mid-wall trophy
  if (roomCols >= 9) {
    items.push({ type: "plant", col: roomCols - 1.5, row: roomRows - 2.25 });  // bottom-right
    // Alternate between trophy and box on right wall midpoint
    const midDecor = (Math.abs(_teamHash) % 2 === 0) ? "trophy" : "box";
    items.push({ type: midDecor, col: roomCols - 1.5, row: Math.floor(roomRows / 2) });
  }

  // Large rooms (12+): fill more wall space
  if (roomCols >= 12) {
    items.push({ type: "bookshelf", col: 0.5, row: Math.floor(roomRows / 2) });     // left wall mid
    items.push({ type: "plant", col: Math.floor(roomCols / 2), row: 0.5 });          // top center
    items.push({ type: "easel", col: Math.floor(roomCols * 0.3), row: roomRows - 2.0 }); // bottom third
  }

  // Extra-large rooms (14+): additional symmetry
  if (roomCols >= 14) {
    items.push({ type: "whiteboard", col: Math.floor(roomCols * 0.7), row: 0.5 });   // top 2/3
    items.push({ type: "box", col: Math.floor(roomCols * 0.7), row: roomRows - 2.0 }); // bottom 2/3
  }

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
    const style = getTeamStyle(teamId);
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
      const accent = getTeamStyle(teamId)?.accent || "#00d4ff";
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
      const markSize = fs(Math.max(9, Math.round(zoom * 4.2)));

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
      const errSize = fs(Math.max(9, Math.round(zoom * 4.2)));
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
  const accent = getTeamStyle(teamId)?.accent || "#fff";
  const displayName = agentName.split("-").map(w => w[0].toUpperCase() + w.slice(1)).join(" ");
  const labelX = Math.round(x) + spriteW + zoom * 2;
  const labelY = Math.round(drawY) + spriteH * 0.15;

  ctx.save();
  ctx.textAlign = "left";
  ctx.textBaseline = "top";

  if (agent.status === "active" || agent.status === "waiting") {
    // ---- Active/Waiting: draw a mini status card to the right ----
    const cardNameSize = fs(Math.max(9, Math.round(zoom * 4.2)));
    const cardTaskSize = fs(Math.max(8, Math.round(zoom * 3.5)));
    ctx.font = `700 ${cardNameSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
    const nameW = ctx.measureText(displayName).width;

    // Task text (truncated)
    const taskText = agent.task ? agent.task.slice(0, 30) + (agent.task.length > 30 ? "…" : "") : "";
    ctx.font = `${cardTaskSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
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
    ctx.font = `700 ${cardNameSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
    ctx.fillStyle = agent.status === "active" ? accent : "#ffae00";
    ctx.fillText(displayName, cardX + cardPadX + zoom * 1.5, cardY + cardPadY);

    // Task text
    if (taskText) {
      ctx.font = `${cardTaskSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
      ctx.fillStyle = "#cbd5e1";
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
    const nameSize = fs(Math.max(9, Math.round(zoom * 4.2)));
    ctx.font = `600 ${nameSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
    ctx.fillStyle = agent.status === "error" ? "#f85149" : "#e2e8f0";
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
  const fontSize = fs(Math.max(9, Math.round(zoom * 4.2)));
  const maxWidth = Math.max(110, zoom * 55);
  const lineHeight = fontSize * 1.35;
  const padding = Math.max(5, zoom * 3);
  const cornerRadius = Math.max(5, zoom * 3);

  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.font = `${fontSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;

  // Collapse newlines/tabs into spaces so they don't render as glyph boxes
  const cleanText = text.replace(/[\n\r\t]+/g, " ").replace(/\s{2,}/g, " ").trim();

  // Word wrap
  const words = cleanText.split(" ");
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
  const by = y - bh - zoom * 5;

  const colors = {
    thinking: { bg: "#0d1b2a", border: "#00d4ff", text: "#e0f2fe", glow: "rgba(0,212,255,0.18)" },
    receiving: { bg: "#1a0c20", border: "#ff6ec7", text: "#fce7f3", glow: "rgba(255,110,199,0.18)" },
    done:      { bg: "#0a1e10", border: "#39ff14", text: "#dcfce7", glow: "rgba(57,255,20,0.15)" },
    error:     { bg: "#1a0808", border: "#f85149", text: "#fecaca", glow: "rgba(248,81,73,0.18)" },
  };
  const c = colors[type] || colors.thinking;

  // Glow halo behind bubble
  ctx.globalAlpha = alpha * 0.35;
  ctx.fillStyle = c.glow;
  ctx.beginPath();
  ctx.roundRect(bx - 3, by - 3, bw + 6, bh + 6, cornerRadius + 3);
  ctx.fill();

  // Bubble background
  ctx.globalAlpha = alpha * 0.94;
  ctx.fillStyle = c.bg;
  ctx.beginPath();
  ctx.roundRect(bx, by, bw, bh, cornerRadius);
  ctx.fill();

  // Border
  ctx.strokeStyle = c.border;
  ctx.lineWidth = Math.max(1.5, zoom * 0.9);
  ctx.globalAlpha = alpha * 0.9;
  ctx.stroke();

  // Tail (small triangle pointing down from bubble center)
  const tailW = Math.max(5, zoom * 4);
  const tailH = Math.max(4, zoom * 3.5);
  ctx.globalAlpha = alpha * 0.94;
  ctx.fillStyle = c.bg;
  ctx.beginPath();
  ctx.moveTo(x - tailW, by + bh);
  ctx.lineTo(x, by + bh + tailH);
  ctx.lineTo(x + tailW, by + bh);
  ctx.fill();
  // Tail border outline
  ctx.strokeStyle = c.border;
  ctx.lineWidth = Math.max(1.5, zoom * 0.9);
  ctx.globalAlpha = alpha * 0.9;
  ctx.beginPath();
  ctx.moveTo(x - tailW, by + bh);
  ctx.lineTo(x, by + bh + tailH);
  ctx.lineTo(x + tailW, by + bh);
  ctx.stroke();

  // Text lines
  ctx.globalAlpha = alpha;
  ctx.fillStyle = c.text;
  ctx.textBaseline = "top";
  ctx.textAlign = "left";
  ctx.font = `${fontSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  for (let i = 0; i < lines.length; i++) {
    ctx.fillText(lines[i], bx + padding, by + padding + i * lineHeight);
  }

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

  const accent = getTeamStyle(agent.team)?.accent || "#00d4ff";
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

// ---- Team Filter ----

function initTeamFilter() {
  const btn = document.getElementById("team-filter-btn");
  const dropdown = document.getElementById("team-filter-dropdown");
  const list = document.getElementById("team-filter-list");
  const badge = document.getElementById("team-filter-badge");
  if (!btn || !dropdown) return;

  // Toggle dropdown
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    dropdown.hidden = !dropdown.hidden;
    if (!dropdown.hidden) _populateFilterList();
  });

  // Close on outside click
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".team-filter")) dropdown.hidden = true;
  });

  // Presets
  document.getElementById("filter-show-all")?.addEventListener("click", () => {
    setHiddenTeams([]);
    _populateFilterList();
    _onFilterChange();
  });

  document.getElementById("filter-pipeline")?.addEventListener("click", () => {
    const pipelineTeams = new Set(
      PIPELINE_STAGES.map(s => STAGE_TO_TEAM[s]).filter(Boolean)
    );
    const hidden = Object.keys(TEAMS).filter(id => !pipelineTeams.has(id));
    setHiddenTeams(hidden);
    _populateFilterList();
    _onFilterChange();
  });

  function _populateFilterList() {
    if (!list) return;
    list.innerHTML = "";
    for (const teamId of Object.keys(TEAMS)) {
      const team = TEAMS[teamId];
      const label = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !isTeamHidden(teamId);
      cb.addEventListener("change", () => {
        const hidden = Object.keys(TEAMS).filter(id => {
          if (id === teamId) return !cb.checked;
          return isTeamHidden(id);
        });
        setHiddenTeams(hidden);
        _onFilterChange();
      });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(` ${team.label || teamId}`));
      list.appendChild(label);
    }
  }

  function _onFilterChange() {
    // Update badge count
    const total = Object.keys(TEAMS).length;
    const visible = getVisibleTeamIds().length;
    if (badge) badge.textContent = visible < total ? `${visible}/${total}` : "";
    // Rebuild layout with only visible teams
    rebuildLayout();
    resize();
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function renderConnection(status) {
  if (connDot) connDot.className = "dot dot--" + (status === "connected" ? "green" : status === "connecting" ? "yellow" : "red");
  if (connText) connText.textContent = status;
}
