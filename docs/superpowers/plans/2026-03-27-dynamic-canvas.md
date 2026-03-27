# Dynamic Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded 2x2/9x9 canvas layout with a dynamic grid engine that handles 1-20+ teams and 1-100+ agents, with progressive disclosure features for large-scale systems.

**Architecture:** Extract layout computation from `renderer.js` into a dedicated section at the top. Replace all hardcoded grid constants (`ROOMS_PER_ROW=2`, `ROOM_COLS=9`, `ROOM_ROWS=9`) with computed values from `computeGrid()` and room sizing functions. Add new state fields for focus mode, collapsed rooms, and flow connectors. All changes are frontend-only — no Python/backend changes needed.

**Tech Stack:** Vanilla JavaScript (Canvas 2D API), CSS custom properties, localStorage persistence

**Spec:** `docs/superpowers/specs/2026-03-27-dynamic-canvas-design.md`

---

## File Structure

### Modified Files

| File | Responsibility | Changes |
|------|---------------|---------|
| `src/pixelpulse/static/modules/renderer.js` | Canvas rendering engine (2,123 lines) | Replace hardcoded grid constants with `computeGrid()`. Parameterize `buildRoomLayout()` with dynamic room dimensions. Add focus mode rendering, collapsed room badges, minimap overlay, flow connector overlay. Extract layout computation to top of file. |
| `src/pixelpulse/static/modules/state.js` | Central state store (399 lines) | Add `focusedRoom`, `collapsedRooms`, `hiddenTeams` state fields. Add `roomSizing` and `showConnectors` to settings-driven state. |
| `src/pixelpulse/static/modules/settings.js` | Settings persistence (273 lines) | Add new defaults: `roomSizing: 'uniform'`, `showConnectors: false`, `orchestratorVisible: true`. |
| `src/pixelpulse/static/modules/settings-panel.js` | Settings UI controller (101 lines) | No code changes — auto-binds via `[data-setting]` attributes in HTML. |
| `src/pixelpulse/static/modules/keyboard.js` | Keyboard shortcuts (93 lines) | Replace hardcoded `TEAM_IDS` array with dynamic team list. Add `F` key toggle for connectors (currently `F` is fitView — remap to `Ctrl+F`). Add number keys 1-9 for focus mode, `0` for overview, `Escape` to exit focus. |
| `src/pixelpulse/static/index.html` | Dashboard markup (259 lines) | Add minimap `<canvas>` element. Add team filter dropdown to topbar. Add new settings controls (room sizing dropdown, connector checkbox, orchestrator toggle). |
| `src/pixelpulse/static/dashboard.css` | Styles (1,367 lines) | Minimap styles, collapsed room badge styles, team filter dropdown styles, focus mode overlay. |

### No New Files

Per spec: all changes within existing files. Layout computation extracted into a clearly-marked section at the top of `renderer.js`, not a new module.

---

## Tasks

### Task 1: Add Dynamic Canvas Settings

**Files:**
- Modify: `src/pixelpulse/static/modules/settings.js:21-36` (DEFAULTS object)
- Modify: `src/pixelpulse/static/index.html:170-210` (settings drawer)

- [ ] **Step 1: Add new settings defaults**

In `settings.js`, add three new keys to the `DEFAULTS` object after `zoomLevel`:

```javascript
const DEFAULTS = Object.freeze({
  theme: 'dark',
  fontScale: 1.0,
  animationSpeed: 1.0,
  scanlinesEnabled: true,
  canvasSmoothing: false,
  sidebarVisible: true,
  bottomBarHeight: 220,
  zoomLevel: 1.0,
  roomSizing: 'uniform',           // 'uniform' | 'adaptive' | 'compact'
  showConnectors: false,            // flow connector overlay
  orchestratorVisible: true,        // show/hide orchestrator zone
  sidebarSections: Object.freeze({
    pipeline: true,
    agents: true,
    runs: true,
    cost: true,
  }),
});
```

- [ ] **Step 2: Add settings controls to HTML**

In `index.html`, inside the settings drawer's Layout section (after the "Default Zoom" range input), add:

```html
<label>Room Sizing:
  <select data-setting="roomSizing">
    <option value="uniform">Uniform</option>
    <option value="adaptive">Adaptive</option>
    <option value="compact">Compact Overflow</option>
  </select>
</label>
<label>Show Flow Connectors:
  <input type="checkbox" data-setting="showConnectors">
</label>
<label>Orchestrator Visible:
  <input type="checkbox" data-setting="orchestratorVisible">
</label>
```

- [ ] **Step 3: Verify settings bind automatically**

The existing `settings-panel.js` auto-binds all `[data-setting]` inputs — no code changes needed there. Open the dashboard in a browser, open settings, and verify:
- Room Sizing dropdown appears with 3 options, defaults to "Uniform"
- Show Flow Connectors checkbox appears, defaults to unchecked
- Orchestrator Visible checkbox appears, defaults to checked
- Changing any value persists after page reload (check localStorage key `pixelpulse-settings`)

- [ ] **Step 4: Commit**

```bash
git add src/pixelpulse/static/modules/settings.js src/pixelpulse/static/index.html
git commit -m "feat: add dynamic canvas settings (room sizing, connectors, orchestrator toggle)"
```

---

### Task 2: Implement Dynamic Grid Computation

**Files:**
- Modify: `src/pixelpulse/static/modules/renderer.js:72-76` (replace constants)
- Modify: `src/pixelpulse/static/modules/renderer.js:663-670` (replace content dimensions)

- [ ] **Step 1: Add layout computation functions**

At the top of `renderer.js`, after the existing `ROOM_GAP = 3` constant (line 75), replace the hardcoded constants with a dynamic layout engine. Remove the lines:

```javascript
// REMOVE these lines (72-76):
const ROOM_COLS = 9;
const ROOM_ROWS = 9;
const ROOM_GAP = 3;
const ROOMS_PER_ROW = 2;
```

Replace with:

```javascript
// ---- Dynamic Layout Engine ----
const ROOM_GAP = 3;          // tiles gap between rooms
const ORCH_ROWS = 3;         // orchestrator zone height in tiles

// Mutable layout state — recomputed by rebuildLayout()
let gridCols = 2;            // number of room columns
let gridRows = 2;            // number of room rows
let roomDims = {};            // { teamId: { cols, rows } }  per-room dimensions
let maxRoomCols = 9;          // widest room in grid (for column alignment)
let maxRoomRows = 9;          // tallest room in grid (for row alignment)
let CONTENT_TILES_W = 30;    // recomputed
let CONTENT_TILES_H = 28;    // recomputed
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
  if (mode === 'compact') return 9;  // fixed size, overflow agents as icons
  // uniform and adaptive use same thresholds, but uniform uses max across all teams
  if (agentCount <= 2) return 7;
  if (agentCount <= 4) return 9;
  if (agentCount <= 8) return 12;
  return 14;
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
  const teamIds = computeTeamOrder(teams, PIPELINE_STAGES, STAGE_TO_TEAM);
  layoutTeamOrder = teamIds;

  const visibleCount = teamIds.length || 1;
  const grid = computeGrid(visibleCount);
  gridCols = grid.cols;
  gridRows = grid.rows;

  const sizingMode = Settings.get('roomSizing') || 'uniform';

  if (sizingMode === 'uniform') {
    // All rooms same size — based on team with most agents
    const maxAgents = Math.max(1, ...teamIds.map(id => (teams[id]?.agents || []).length));
    const uniformSize = computeRoomSize(maxAgents, 'uniform');
    roomDims = {};
    for (const id of teamIds) {
      roomDims[id] = { cols: uniformSize, rows: uniformSize };
    }
    maxRoomCols = uniformSize;
    maxRoomRows = uniformSize;
  } else {
    // Adaptive or compact — per-room sizing
    roomDims = {};
    let widest = 7, tallest = 7;
    for (const id of teamIds) {
      const agentCount = (teams[id]?.agents || []).length;
      const size = computeRoomSize(agentCount, sizingMode);
      roomDims[id] = { cols: size, rows: size };
      if (size > widest) widest = size;
      if (size > tallest) tallest = size;
    }
    // For grid alignment: each column uses widest room in that column,
    // each row uses tallest room in that row
    maxRoomCols = widest;
    maxRoomRows = tallest;
  }

  // Orchestrator zone: 1 row of teams → below, 2+ rows → dedicated row
  const orchHeight = Settings.get('orchestratorVisible') !== false
    ? ORCH_ROWS + 1   // +1 gap tile
    : 0;

  // Content bounds
  CONTENT_TILES_W = PAD_LEFT + gridCols * maxRoomCols + (gridCols - 1) * ROOM_GAP + PAD_RIGHT;
  CONTENT_TILES_H = PAD_TOP + gridRows * maxRoomRows + (gridRows - 1) * ROOM_GAP + orchHeight + PAD_BOTTOM;
}
```

- [ ] **Step 2: Remove old hardcoded CONTENT_TILES dimensions**

Delete the old computed constants at lines 668-670:

```javascript
// REMOVE these lines:
const CONTENT_TILES_W = PAD_LEFT + ROOMS_PER_ROW * ROOM_COLS + ROOM_GAP + PAD_RIGHT;
const CONTENT_TILES_H = PAD_TOP + 2 * ROOM_ROWS + ROOM_GAP + PAD_BOTTOM;
```

These are now `let` variables managed by `rebuildLayout()`.

- [ ] **Step 3: Update render() to use dynamic grid**

In the `render()` function (line 820), replace the room positioning loop:

```javascript
// OLD (lines 854-859):
for (let i = 0; i < teamEntries.length; i++) {
    const [teamId, team] = teamEntries[i];
    const roomCol = i % ROOMS_PER_ROW;
    const roomRow = Math.floor(i / ROOMS_PER_ROW);
    const rx = offsetX + roomCol * (ROOM_COLS + ROOM_GAP) * s;
    const ry = offsetY + roomRow * (ROOM_ROWS + ROOM_GAP) * s;
```

Replace with:

```javascript
for (let i = 0; i < layoutTeamOrder.length; i++) {
    const teamId = layoutTeamOrder[i];
    const team = TEAMS[teamId];
    if (!team) continue;
    const roomCol = i % gridCols;
    const roomRow = Math.floor(i / gridCols);
    const dims = roomDims[teamId] || { cols: 9, rows: 9 };
    const rx = offsetX + roomCol * (maxRoomCols + ROOM_GAP) * s;
    const ry = offsetY + roomRow * (maxRoomRows + ROOM_GAP) * s;
```

- [ ] **Step 4: Update drawRoom() to accept dynamic dimensions**

Change `drawRoom(rx, ry, teamId)` signature to `drawRoom(rx, ry, teamId, roomCols, roomRows)` and replace all internal `ROOM_COLS` / `ROOM_ROWS` references with the parameters. The call site becomes:

```javascript
drawRoom(rx, ry, teamId, dims.cols, dims.rows);
```

Inside `drawRoom`, replace every `ROOM_COLS` with `roomCols` and every `ROOM_ROWS` with `roomRows`. The function currently uses these in:
- Floor checkerboard loop: `for r < ROOM_ROWS`, `for c < ROOM_COLS`
- Wall drawing: `ROOM_COLS * s` for width, `ROOM_ROWS * s` for height
- Accent glow: `ROOM_COLS * s` width
- Active stage highlight: `ROOM_COLS * s`, `ROOM_ROWS * s`

- [ ] **Step 5: Update totalW for orchestrator zone**

Replace the orchestrator width calculation:

```javascript
// OLD:
const totalW = (ROOMS_PER_ROW * ROOM_COLS + ROOM_GAP) * s;

// NEW:
const totalW = (gridCols * maxRoomCols + (gridCols - 1) * ROOM_GAP) * s;
```

- [ ] **Step 6: Call rebuildLayout() on init and config change**

In the `init()` function of renderer.js, call `rebuildLayout()` after config is loaded. Also subscribe to settings changes:

```javascript
// In init(), after loadConfig() resolves:
rebuildLayout();

// Subscribe to layout-affecting settings
Settings.onChange('roomSizing', () => { rebuildLayout(); resize(); });
Settings.onChange('orchestratorVisible', () => { rebuildLayout(); resize(); });
```

Also call `rebuildLayout()` when new config arrives via WebSocket (in the config message handler in `ws-client.js` or `state.js`).

- [ ] **Step 7: Verify 4-team backward compatibility**

Open the dashboard with the default 4-team config. Verify:
- `computeGrid(4)` returns `{ cols: 2, rows: 2 }` — same 2x2 layout
- `computeRoomSize(4, 'uniform')` returns `9` — same 9x9 rooms
- Content dimensions: `1 + 2*9 + 1*3 + 5 = 27` wide, similar to old 30 (padding may differ slightly)
- Dashboard renders identically to before

- [ ] **Step 8: Commit**

```bash
git add src/pixelpulse/static/modules/renderer.js
git commit -m "feat: dynamic grid computation engine replacing hardcoded 2x2 layout"
```

---

### Task 3: Parameterize buildRoomLayout() for Dynamic Room Sizes

**Files:**
- Modify: `src/pixelpulse/static/modules/renderer.js:1206-1261` (buildRoomLayout function)

- [ ] **Step 1: Update buildRoomLayout() signature**

Change `buildRoomLayout(team, teamId)` to accept room dimensions:

```javascript
function buildRoomLayout(team, teamId, roomCols, roomRows) {
```

- [ ] **Step 2: Replace all ROOM_COLS/ROOM_ROWS inside the function**

The function uses `ROOM_COLS` and `ROOM_ROWS` in these places:
- `startCol` centering: `(ROOM_COLS - gridW - 2) / 2` → `(roomCols - gridW - 2) / 2`
- `startRow` centering: `(ROOM_ROWS - gridH - 1) / 2` → `(roomRows - gridH - 1) / 2`
- Decoration placement: `ROOM_COLS - 1.5` → `roomCols - 1.5`
- Bookshelf placement: `ROOM_ROWS - 2.25` → `roomRows - 2.25`

Full updated function body:

```javascript
function buildRoomLayout(team, teamId, roomCols, roomRows) {
  const agents = team.agents;
  const items = [];

  const cols = Math.min(agents.length, 2);
  const rows = Math.ceil(agents.length / 2);
  const deskSpacingX = 4;
  const deskSpacingY = 2.4;
  const agentOffset = 1.9;
  const gridW = cols > 1 ? deskSpacingX : 0;
  const gridH = (rows - 1) * deskSpacingY + agentOffset;
  const startCol = (roomCols - gridW - 2) / 2;
  const startRow = (roomRows - gridH - 1) / 2 + agentOffset;

  for (let i = 0; i < agents.length; i++) {
    const col = startCol + (i % 2) * deskSpacingX;
    const row = startRow + Math.floor(i / 2) * deskSpacingY;
    const deskCenterCol = col + 0.4;
    const agentDeskRow = row - agentOffset;

    initRoam(agents[i], deskCenterCol, agentDeskRow, teamId);

    const agent = getAgent(agents[i]);
    const rs = roamState[agents[i]];
    const isRoaming = rs && agent?.status === "idle" && rs.state !== "seated";
    const agentCol = isRoaming ? rs.col : deskCenterCol;
    const agentRow = isRoaming ? rs.row : agentDeskRow;

    items.push({ type: "agent", col: agentCol, row: agentRow, agent: agents[i], roaming: isRoaming });
    items.push({ type: "monitor", col: deskCenterCol, row: row - 0.15 });
    items.push({ type: "desk", col, row });
  }

  // Decorations — scale with room size
  const teamDecor = { research: "whiteboard", design: "easel", commerce: "box", learning: "trophy" };
  const decor = teamDecor[teamId];
  items.push({ type: "plant", col: 0.5, row: 0.5 });
  if (decor) {
    items.push({ type: decor, col: roomCols - 1.5, row: 0.5 });
  }
  items.push({ type: "bookshelf", col: 0.5, row: roomRows - 2.25 });

  // Extra furniture for larger rooms (spec: 12-tile → 5-6, 14-tile → 6-8)
  if (roomCols >= 12) {
    items.push({ type: "plant", col: roomCols - 1.5, row: roomRows - 2.25 });
    items.push({ type: "bookshelf", col: roomCols - 1.5, row: Math.floor(roomRows / 2) });
  }
  if (roomCols >= 14) {
    items.push({ type: "plant", col: Math.floor(roomCols / 2), row: 0.5 });
    items.push({ type: "bookshelf", col: 0.5, row: Math.floor(roomRows / 2) });
  }

  _registerFurniture(teamId, items);
  return items;
}
```

- [ ] **Step 3: Update the call site in render()**

Where `buildRoomLayout` is called in `render()`, pass the room dimensions:

```javascript
const items = buildRoomLayout(team, teamId, dims.cols, dims.rows);
```

- [ ] **Step 4: Update roaming bounds**

The roaming system uses `WALL_MIN_COL`, `WALL_MAX_COL`, `WALL_MIN_ROW`, `WALL_MAX_ROW` constants (currently derived from `ROOM_COLS=9`, `ROOM_ROWS=9`). These need to become per-room:

Replace the constants:
```javascript
// REMOVE:
const WALL_MIN_COL = 1.2;
const WALL_MAX_COL = ROOM_COLS - 1.8;  // 7.2
const WALL_MIN_ROW = 1.2;
const WALL_MAX_ROW = ROOM_ROWS - 1.8;  // 7.2
```

With a function:
```javascript
function getRoomBounds(teamId) {
  const dims = roomDims[teamId] || { cols: 9, rows: 9 };
  return {
    minCol: 1.2,
    maxCol: dims.cols - 1.8,
    minRow: 1.2,
    maxRow: dims.rows - 1.8,
  };
}
```

Then update all roaming functions (`_isBlocked`, `_moveWithCollision`, `tickRoaming`, etc.) to call `getRoomBounds(rs.roomTeamId)` instead of using the old constants.

- [ ] **Step 5: Verify with demo mode**

Run the dashboard in demo mode. Verify:
- Agents sit centered in their rooms
- Decorations are in corners
- Roaming agents stay within room boundaries
- No visual regression from the 4-team default

- [ ] **Step 6: Commit**

```bash
git add src/pixelpulse/static/modules/renderer.js
git commit -m "feat: parameterize room layout and roaming for dynamic room sizes"
```

---

### Task 4: Update drawRoomLabel() and Orchestrator Zone

**Files:**
- Modify: `src/pixelpulse/static/modules/renderer.js` (drawRoomLabel ~line 960, drawOrchestratorZone ~line 1060)

- [ ] **Step 1: Parameterize drawRoomLabel()**

The `drawRoomLabel()` function draws the team name above each room. It uses `ROOM_COLS` for centering. Update its signature:

```javascript
// OLD:
function drawRoomLabel(rx, ry, team, teamId)

// NEW:
function drawRoomLabel(rx, ry, team, teamId, roomCols)
```

Inside, replace `ROOM_COLS` with `roomCols`:
- Label centering: `rx + (ROOM_COLS * s) / 2` → `rx + (roomCols * s) / 2`
- Agent count badge positioning: same pattern

Update the call site in `render()`:
```javascript
drawRoomLabel(rx, ry, team, teamId, dims.cols);
```

- [ ] **Step 2: Update orchestrator zone positioning**

The `drawOrchestratorZone()` function is called with `(offsetX, offsetY, totalW, s)`. Its Y position needs to account for variable grid rows. Currently it hardcodes the position between row 0 and row 1 of a 2-row grid.

Update the zone positioning to use the dynamic grid:

```javascript
function drawOrchestratorZone(offsetX, offsetY, totalW, s) {
  if (Settings.get('orchestratorVisible') === false) return;

  // Position: between first row and rest (for 2+ rows),
  // or below single row
  const firstRowBottom = offsetY + maxRoomRows * s;
  const zx = offsetX;
  const zy = firstRowBottom + s * 0.5;  // half tile gap
  const zw = totalW;
  const zh = ORCH_ROWS * s;

  // ... rest of existing drawing code with zx, zy, zw, zh ...
}
```

- [ ] **Step 3: Offset subsequent room rows below orchestrator**

In `render()`, room rows after the first need to account for the orchestrator zone height. Update the `ry` calculation:

```javascript
const orchOffset = (Settings.get('orchestratorVisible') !== false && gridRows > 1)
  ? (ORCH_ROWS + 1)  // orchestrator zone + gap tile
  : 0;

// Room Y position:
let ry;
if (roomRow === 0) {
  ry = offsetY;
} else {
  ry = offsetY + maxRoomRows * s                        // first row height
     + orchOffset * s                                    // orchestrator zone
     + (roomRow - 1) * (maxRoomRows + ROOM_GAP) * s;   // subsequent rows
}
```

- [ ] **Step 4: Verify orchestrator renders correctly**

Open dashboard with 4 teams. Verify:
- Orchestrator timeline renders between row 1 and row 2
- Pipeline stage nodes are properly spaced across `totalW`
- Toggling "Orchestrator Visible" OFF in settings hides the zone and rooms move up

- [ ] **Step 5: Commit**

```bash
git add src/pixelpulse/static/modules/renderer.js
git commit -m "feat: dynamic orchestrator zone positioning and parameterized room labels"
```

---

### Task 5: Add Dynamic Canvas State Fields

**Files:**
- Modify: `src/pixelpulse/static/modules/state.js` (state object and exports)

- [ ] **Step 1: Add canvas state fields**

In `state.js`, add new fields to the state object (after the existing `connection` field):

```javascript
const state = {
  // ... existing fields ...
  connection: "disconnected",

  // Dynamic canvas state
  focusedRoom: null,          // teamId of focused room, or null
  collapsedRooms: new Set(),  // Set of collapsed teamId strings
  hiddenTeams: new Set(),     // Set of hidden teamId strings (team filter)
};
```

- [ ] **Step 2: Add state accessor/mutator functions**

Add exported functions for the new state fields:

```javascript
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
```

- [ ] **Step 3: Load persisted collapsed state on init**

In the `loadConfig()` function (or right after it), restore collapsed rooms from localStorage:

```javascript
// After config is loaded:
try {
  const saved = localStorage.getItem('pixelpulse-collapsed');
  if (saved) {
    const ids = JSON.parse(saved);
    for (const id of ids) state.collapsedRooms.add(id);
  }
} catch { /* ignore corrupt data */ }
```

- [ ] **Step 4: Commit**

```bash
git add src/pixelpulse/static/modules/state.js
git commit -m "feat: add focus mode, collapsed rooms, and team filter state"
```

---

### Task 6: Focus Mode (Priority 1 — Must Have)

**Files:**
- Modify: `src/pixelpulse/static/modules/renderer.js` (render loop, mouse handlers)
- Modify: `src/pixelpulse/static/modules/keyboard.js` (number keys, Escape)

- [ ] **Step 1: Add double-click handler for focus mode**

In renderer.js, in the canvas mouse event setup (init function), add a dblclick handler:

```javascript
canvas.addEventListener("dblclick", (e) => {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const cx = (e.clientX - rect.left) * dpr;
  const cy = (e.clientY - rect.top) * dpr;

  // Hit test: which room was clicked?
  const clickedTeam = hitTestRoom(cx, cy);

  if (clickedTeam) {
    const current = getFocusedRoom();
    if (current === clickedTeam) {
      // Double-click focused room → exit focus
      setFocusedRoom(null);
      fitView();
    } else {
      setFocusedRoom(clickedTeam);
      zoomToRoom(clickedTeam);
    }
  } else {
    // Click outside any room → exit focus
    if (getFocusedRoom()) {
      setFocusedRoom(null);
      fitView();
    }
  }
});
```

- [ ] **Step 2: Implement hitTestRoom()**

Add a function that maps canvas coordinates to a team room:

```javascript
function hitTestRoom(cx, cy) {
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

  for (let i = 0; i < layoutTeamOrder.length; i++) {
    const teamId = layoutTeamOrder[i];
    const col = i % gridCols;
    const row = Math.floor(i / gridCols);
    const dims = roomDims[teamId] || { cols: 9, rows: 9 };
    const rx = offsetX + col * (maxRoomCols + ROOM_GAP) * s;
    const ry = offsetY + row * (maxRoomRows + ROOM_GAP) * s;
    // Account for orchestrator offset on row > 0
    const orchOffset = (Settings.get('orchestratorVisible') !== false && gridRows > 1)
      ? (ORCH_ROWS + 1) : 0;
    const adjustedRy = row === 0 ? ry : ry + orchOffset * s;

    if (cx >= rx && cx <= rx + dims.cols * s &&
        cy >= adjustedRy && cy <= adjustedRy + dims.rows * s) {
      return teamId;
    }
  }
  return null;
}
```

- [ ] **Step 3: Implement zoomToRoom()**

Smoothly zoom the canvas to fill the viewport with one room:

```javascript
function zoomToRoom(teamId) {
  const idx = layoutTeamOrder.indexOf(teamId);
  if (idx < 0) return;

  const dims = roomDims[teamId] || { cols: 9, rows: 9 };
  const dpr = window.devicePixelRatio || 1;
  const wrap = document.querySelector(".canvas-wrap");
  const vw = wrap.clientWidth * dpr;
  const vh = wrap.clientHeight * dpr;

  // Zoom so the room fills ~80% of viewport
  const targetZoomW = (vw * 0.8) / (dims.cols * TILE_SIZE);
  const targetZoomH = (vh * 0.8) / (dims.rows * TILE_SIZE);
  userZoom = Math.min(targetZoomW, targetZoomH) / baseZoom;
  zoom = baseZoom * userZoom;

  // Pan to center the room
  const col = idx % gridCols;
  const row = Math.floor(idx / gridCols);
  const roomCenterX = (PAD_LEFT + col * (maxRoomCols + ROOM_GAP) + dims.cols / 2) * TILE_SIZE;
  const roomCenterY = (PAD_TOP + row * (maxRoomRows + ROOM_GAP) + dims.rows / 2) * TILE_SIZE;
  const contentCenterX = (CONTENT_TILES_W / 2) * TILE_SIZE;
  const contentCenterY = (CONTENT_TILES_H / 2) * TILE_SIZE;

  panX = (contentCenterX - roomCenterX) * zoom / dpr;
  panY = (contentCenterY - roomCenterY) * zoom / dpr;
}
```

- [ ] **Step 4: Render focus mode overlay**

In `render()`, after drawing all rooms but before particles/bubbles, add focus dimming:

```javascript
// After drawing all rooms and furniture, before particles:
const focused = getFocusedRoom();
if (focused) {
  // Dim all rooms except the focused one
  ctx.save();
  ctx.fillStyle = "rgba(0, 0, 0, 0.8)";
  ctx.fillRect(0, 0, w, h);
  ctx.restore();

  // Redraw ONLY the focused room on top of the dim overlay
  const focusIdx = layoutTeamOrder.indexOf(focused);
  if (focusIdx >= 0) {
    const focusTeam = TEAMS[focused];
    const focusDims = roomDims[focused] || { cols: 9, rows: 9 };
    const col = focusIdx % gridCols;
    const row = Math.floor(focusIdx / gridCols);
    const rx = offsetX + col * (maxRoomCols + ROOM_GAP) * s;
    const ry = /* use same ry calculation with orchOffset */;

    drawRoom(rx, ry, focused, focusDims.cols, focusDims.rows);
    drawRoomLabel(rx, ry, focusTeam, focused, focusDims.cols);
    const items = buildRoomLayout(focusTeam, focused, focusDims.cols, focusDims.rows);
    // Draw items same as main loop...
    for (const item of items) {
      const ix = rx + item.col * s;
      const iy = ry + item.row * s;
      // draw based on item.type (same switch as main loop)
    }
  }
}
```

Note: The "redraw focused room" block reuses the same sprite drawing logic from the main render loop. Extract the drawable rendering switch into a helper `drawDrawable(d)` to avoid duplication.

- [ ] **Step 5: Update keyboard.js for focus mode**

Replace the hardcoded `TEAM_IDS` array and add focus shortcuts:

```javascript
// Replace:
const TEAM_IDS = ["research", "design", "commerce", "learning"];

// With dynamic import:
import { getVisibleTeamIds, getFocusedRoom, setFocusedRoom } from "./state.js";
```

Update the number key handler:

```javascript
case "1": case "2": case "3": case "4":
case "5": case "6": case "7": case "8": case "9": {
  e.preventDefault();
  const idx = parseInt(e.key) - 1;
  const teamIds = getVisibleTeamIds();
  if (idx < teamIds.length) {
    setFocusedRoom(teamIds[idx]);
    // zoomToRoom imported from renderer.js
    if (_zoomToRoom) _zoomToRoom(teamIds[idx]);
  }
  break;
}

case "0":
  e.preventDefault();
  setFocusedRoom(null);
  fitView();
  break;

case "Escape":
  if (getFocusedRoom()) {
    e.preventDefault();
    setFocusedRoom(null);
    fitView();
  }
  break;
```

- [ ] **Step 6: Export zoomToRoom from renderer.js**

Add `zoomToRoom` to the renderer.js exports so keyboard.js can import it:

```javascript
export { zoomToRoom };
```

And in keyboard.js, lazy-import it:

```javascript
let _zoomToRoom = null;
import("./renderer.js").then((mod) => {
  if (typeof mod.panToTeam === "function") _panToTeam = mod.panToTeam;
  if (typeof mod.zoomToRoom === "function") _zoomToRoom = mod.zoomToRoom;
});
```

- [ ] **Step 7: Verify focus mode**

Test in browser:
- Double-click a room → zooms in, other rooms dimmed
- Press Escape → returns to overview
- Press 1-4 → focuses rooms by position
- Press 0 → returns to overview
- Double-click focused room → exits focus

- [ ] **Step 8: Commit**

```bash
git add src/pixelpulse/static/modules/renderer.js src/pixelpulse/static/modules/keyboard.js src/pixelpulse/static/modules/state.js
git commit -m "feat: focus mode — double-click room to zoom, ESC to return, number keys 1-9"
```

---

### Task 7: Collapsible Rooms (Priority 2)

**Files:**
- Modify: `src/pixelpulse/static/modules/renderer.js` (render loop, click handler)

- [ ] **Step 1: Add click handler for room header collapse**

In the canvas click handler (not dblclick), detect clicks on the room label area (the PAD_TOP zone above each room):

```javascript
canvas.addEventListener("click", (e) => {
  // ... existing click logic ...

  // Room header collapse detection
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const cx = (e.clientX - rect.left) * dpr;
  const cy = (e.clientY - rect.top) * dpr;
  const s = TILE_SIZE * zoom;

  for (let i = 0; i < layoutTeamOrder.length; i++) {
    const teamId = layoutTeamOrder[i];
    const col = i % gridCols;
    const row = Math.floor(i / gridCols);
    const rx = offsetX + col * (maxRoomCols + ROOM_GAP) * s;
    const ry = /* room Y with orch offset */;
    const labelY = ry - s * 1.5;  // label sits above room
    const labelH = s * 1.5;
    const labelW = (roomDims[teamId]?.cols || 9) * s;

    if (cx >= rx && cx <= rx + labelW && cy >= labelY && cy <= labelY + labelH) {
      toggleRoomCollapsed(teamId);
      break;
    }
  }
});
```

Note: Need to store the computed `offsetX`/`offsetY` from `render()` as module-level variables so click handlers can access them. Add `let lastOffsetX = 0, lastOffsetY = 0;` and set them in render().

- [ ] **Step 2: Draw collapsed room badge**

In the render loop, when a room is collapsed, draw a compact badge instead of the full room:

```javascript
for (let i = 0; i < layoutTeamOrder.length; i++) {
  const teamId = layoutTeamOrder[i];
  const team = TEAMS[teamId];
  if (!team) continue;

  const dims = roomDims[teamId] || { cols: 9, rows: 9 };
  const rx = /* computed */;
  const ry = /* computed */;

  if (isRoomCollapsed(teamId)) {
    // Draw collapsed badge: 3 tiles wide × 1 tile tall
    drawCollapsedBadge(rx, ry, teamId, team, s);
    continue;  // skip full room rendering
  }

  // ... normal room rendering ...
}
```

- [ ] **Step 3: Implement drawCollapsedBadge()**

```javascript
function drawCollapsedBadge(rx, ry, teamId, team, s) {
  const style = TEAM_STYLES[teamId] || TEAM_STYLES.research;
  const badgeW = 3 * s;
  const badgeH = 1 * s;

  // Background
  ctx.fillStyle = style.floor1;
  ctx.fillRect(rx, ry, badgeW, badgeH);

  // Border with accent
  ctx.strokeStyle = style.accent;
  ctx.lineWidth = 2;
  ctx.strokeRect(rx, ry, badgeW, badgeH);

  // Team name
  const fontSize = Math.max(8, Math.round(8 * zoom * 0.5));
  ctx.font = `bold ${fontSize}px "JetBrains Mono", monospace`;
  ctx.fillStyle = style.accent;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(team.name || teamId, rx + s * 0.3, ry + badgeH / 2);

  // Agent count
  const count = (team.agents || []).length;
  ctx.textAlign = "right";
  ctx.fillStyle = "#94a3b8";
  ctx.fillText(`${count}`, rx + badgeW - s * 0.3, ry + badgeH / 2);

  // Active indicator (pulsing dot if any agent is working)
  const hasActive = team.agents.some(n => {
    const a = getAgent(n);
    return a && a.status === "active";
  });
  if (hasActive) {
    const pulse = 0.5 + 0.5 * Math.sin(tick * 0.08);
    ctx.fillStyle = style.accent;
    ctx.globalAlpha = pulse;
    ctx.beginPath();
    ctx.arc(rx + badgeW - s * 0.7, ry + badgeH / 2, 3 * zoom, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }
}
```

- [ ] **Step 4: Verify collapsed rooms**

Test:
- Click a room label → room collapses to a small badge
- Click the badge → room expands back
- Collapsed state persists after page reload
- Active agents still show pulsing dot on badge
- Grid layout stays stable (other rooms don't move)

- [ ] **Step 5: Commit**

```bash
git add src/pixelpulse/static/modules/renderer.js
git commit -m "feat: collapsible rooms — click header to collapse/expand with persisted state"
```

---

### Task 8: Flow Connectors (Optional Overlay)

**Files:**
- Modify: `src/pixelpulse/static/modules/renderer.js` (add connector drawing after rooms)
- Modify: `src/pixelpulse/static/modules/keyboard.js` (F key toggle)

- [ ] **Step 1: Implement drawFlowConnectors()**

Add after the orchestrator zone draw, before z-sorted drawables:

```javascript
function drawFlowConnectors(offsetX, offsetY, s) {
  if (!Settings.get('showConnectors')) return;
  if (!PIPELINE_STAGES || PIPELINE_STAGES.length <= 1) return;

  ctx.save();
  ctx.setLineDash([6 * zoom, 4 * zoom]);
  ctx.lineWidth = Math.max(1, zoom);
  ctx.lineCap = "round";

  // Collect room centers in pipeline order
  const centers = [];
  for (const stage of PIPELINE_STAGES) {
    const teamId = STAGE_TO_TEAM[stage];
    if (!teamId) continue;
    const idx = layoutTeamOrder.indexOf(teamId);
    if (idx < 0) continue;

    const col = idx % gridCols;
    const row = Math.floor(idx / gridCols);
    const dims = roomDims[teamId] || { cols: 9, rows: 9 };
    const rx = offsetX + col * (maxRoomCols + ROOM_GAP) * s;
    const ry = /* computed with orch offset */;
    const cx = rx + (dims.cols / 2) * s;
    const cy = ry + (dims.rows / 2) * s;

    const style = TEAM_STYLES[teamId] || TEAM_STYLES.research;
    centers.push({ x: cx, y: cy, color: style.accent });
  }

  // Draw lines between consecutive centers
  for (let i = 0; i < centers.length - 1; i++) {
    const from = centers[i];
    const to = centers[i + 1];

    ctx.strokeStyle = from.color;
    ctx.globalAlpha = 0.3;

    ctx.beginPath();
    ctx.moveTo(from.x, from.y);

    // Rounded path: if rooms are in different rows, use an L-bend
    if (Math.abs(from.y - to.y) > s) {
      const midX = (from.x + to.x) / 2;
      ctx.lineTo(midX, from.y);
      ctx.lineTo(midX, to.y);
      ctx.lineTo(to.x, to.y);
    } else {
      ctx.lineTo(to.x, to.y);
    }
    ctx.stroke();
  }

  ctx.globalAlpha = 1;
  ctx.setLineDash([]);
  ctx.restore();
}
```

- [ ] **Step 2: Call drawFlowConnectors in render()**

In `render()`, call after drawing rooms but before drawables:

```javascript
// After room rendering loop, before z-sort:
drawFlowConnectors(offsetX, offsetY, s);
```

- [ ] **Step 3: Add F key toggle in keyboard.js**

Currently `F` triggers `fitView()`. Remap:
- `F` → toggle flow connectors
- `Shift+F` → fitView (was just `F`)

```javascript
case "f":
  e.preventDefault();
  if (e.shiftKey) {
    fitView();
  } else {
    Settings.set('showConnectors', !Settings.get('showConnectors'));
  }
  break;

case "F":
  e.preventDefault();
  if (e.shiftKey) {
    fitView();
  } else {
    Settings.set('showConnectors', !Settings.get('showConnectors'));
  }
  break;
```

Actually simpler — handle both cases in one block since `e.key` is `f` or `F` based on shift:

```javascript
case "f":
case "F":
  e.preventDefault();
  Settings.set('showConnectors', !Settings.get('showConnectors'));
  break;
```

And remap fitView to a different key — keep the existing `Ctrl+0` or double-click behavior as the primary fit-view trigger (the fit button in canvas controls already exists).

- [ ] **Step 4: Verify connectors**

Test:
- Press F → dashed lines appear between pipeline rooms
- Press F again → lines disappear
- Lines follow room centers with L-bends for different rows
- Lines use team accent colors at 30% opacity
- Setting persists in settings panel checkbox

- [ ] **Step 5: Commit**

```bash
git add src/pixelpulse/static/modules/renderer.js src/pixelpulse/static/modules/keyboard.js
git commit -m "feat: flow connectors — dashed pipeline overlay toggled with F key"
```

---

### Task 9: Minimap (Priority 3)

**Files:**
- Modify: `src/pixelpulse/static/index.html` (add minimap canvas)
- Modify: `src/pixelpulse/static/dashboard.css` (minimap styles)
- Modify: `src/pixelpulse/static/modules/renderer.js` (minimap rendering + interaction)

- [ ] **Step 1: Add minimap canvas element**

In `index.html`, inside `.canvas-wrap` (after the existing `<canvas id="office-canvas">`), add:

```html
<canvas id="minimap-canvas" class="minimap" width="160" height="100"></canvas>
```

- [ ] **Step 2: Add minimap CSS**

In `dashboard.css`, add:

```css
.minimap {
  position: absolute;
  bottom: 12px;
  right: 12px;
  width: 160px;
  height: 100px;
  border: 1px solid var(--border-glow);
  border-radius: 6px;
  background: rgba(8, 12, 20, 0.85);
  backdrop-filter: blur(8px);
  pointer-events: auto;
  cursor: pointer;
  z-index: 10;
  display: none;  /* hidden by default, shown when content exceeds viewport */
}
```

- [ ] **Step 3: Implement minimap rendering**

In renderer.js, add a `drawMinimap()` function called at the end of `render()`:

```javascript
function drawMinimap() {
  const mm = document.getElementById("minimap-canvas");
  if (!mm) return;

  // Only show minimap when content exceeds viewport (user would need to pan/zoom)
  const needsMinimap = userZoom > 1.2 || panX !== 0 || panY !== 0 ||
    (gridCols > 3 || gridRows > 2);
  mm.style.display = needsMinimap ? "block" : "none";
  if (!needsMinimap) return;

  const mCtx = mm.getContext("2d");
  const mw = mm.width;
  const mh = mm.height;
  mCtx.clearRect(0, 0, mw, mh);

  // Scale: fit all content tiles into minimap
  const scaleX = mw / CONTENT_TILES_W;
  const scaleY = mh / CONTENT_TILES_H;
  const scale = Math.min(scaleX, scaleY);

  // Draw simplified room rectangles
  for (let i = 0; i < layoutTeamOrder.length; i++) {
    const teamId = layoutTeamOrder[i];
    const col = i % gridCols;
    const row = Math.floor(i / gridCols);
    const dims = roomDims[teamId] || { cols: 9, rows: 9 };
    const style = TEAM_STYLES[teamId] || TEAM_STYLES.research;

    const rx = (PAD_LEFT + col * (maxRoomCols + ROOM_GAP)) * scale;
    const ry = (PAD_TOP + row * (maxRoomRows + ROOM_GAP)) * scale;
    const rw = dims.cols * scale;
    const rh = dims.rows * scale;

    mCtx.fillStyle = style.accent;
    mCtx.globalAlpha = isRoomCollapsed(teamId) ? 0.2 : 0.5;
    mCtx.fillRect(rx, ry, rw, rh);
    mCtx.globalAlpha = 1;
  }

  // Draw viewport rectangle (white outline)
  const dpr = window.devicePixelRatio || 1;
  const s = TILE_SIZE * zoom;
  const contentW = CONTENT_TILES_W * s;
  const contentH = CONTENT_TILES_H * s;
  const vpLeft = (canvas.width / 2 - panX * dpr) / contentW * CONTENT_TILES_W;
  const vpTop = (canvas.height / 2 - panY * dpr) / contentH * CONTENT_TILES_H;
  const vpW = (canvas.width / contentW) * CONTENT_TILES_W;
  const vpH = (canvas.height / contentH) * CONTENT_TILES_H;

  mCtx.strokeStyle = "#ffffff";
  mCtx.lineWidth = 1.5;
  mCtx.strokeRect(
    (vpLeft - vpW / 2) * scale,
    (vpTop - vpH / 2) * scale,
    vpW * scale,
    vpH * scale
  );
}
```

- [ ] **Step 4: Add minimap click-to-pan**

```javascript
function initMinimap() {
  const mm = document.getElementById("minimap-canvas");
  if (!mm) return;

  mm.addEventListener("click", (e) => {
    const rect = mm.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    // Convert minimap coordinates to content tile coordinates
    const scaleX = mm.width / CONTENT_TILES_W;
    const scaleY = mm.height / CONTENT_TILES_H;
    const scale = Math.min(scaleX, scaleY);

    const tileX = mx / scale;
    const tileY = my / scale;

    // Pan main canvas to center on this position
    const dpr = window.devicePixelRatio || 1;
    const centerTileX = CONTENT_TILES_W / 2;
    const centerTileY = CONTENT_TILES_H / 2;
    panX = (centerTileX - tileX) * TILE_SIZE * zoom / dpr;
    panY = (centerTileY - tileY) * TILE_SIZE * zoom / dpr;
  });
}
```

Call `initMinimap()` from the main `init()` function.

- [ ] **Step 5: Call drawMinimap() in render()**

At the very end of `render()`:

```javascript
drawMinimap();
```

- [ ] **Step 6: Verify minimap**

Test:
- With 4 teams (default): minimap hidden (content fits viewport)
- Zoom in → minimap appears showing room positions + viewport rectangle
- Click minimap → main canvas pans to clicked position
- With 8+ teams: minimap auto-shows

- [ ] **Step 7: Commit**

```bash
git add src/pixelpulse/static/modules/renderer.js src/pixelpulse/static/index.html src/pixelpulse/static/dashboard.css
git commit -m "feat: minimap overlay with click-to-pan and auto-hide"
```

---

### Task 10: Team Filter (Priority 4)

**Files:**
- Modify: `src/pixelpulse/static/index.html` (topbar dropdown)
- Modify: `src/pixelpulse/static/dashboard.css` (dropdown styles)
- Modify: `src/pixelpulse/static/modules/renderer.js` (filter integration with layout)

- [ ] **Step 1: Add team filter dropdown to topbar HTML**

In `index.html`, in the `.topbar` section (after the demo button area), add:

```html
<div class="team-filter" id="team-filter">
  <button class="btn btn--sm" id="team-filter-btn">
    Teams <span id="team-filter-badge"></span>
  </button>
  <div class="team-filter__dropdown" id="team-filter-dropdown" hidden>
    <div class="team-filter__presets">
      <button class="btn btn--xs" id="filter-show-all">Show All</button>
      <button class="btn btn--xs" id="filter-pipeline">Pipeline Only</button>
    </div>
    <div class="team-filter__list" id="team-filter-list">
      <!-- Populated dynamically -->
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add team filter CSS**

In `dashboard.css`:

```css
.team-filter {
  position: relative;
}

.team-filter__dropdown {
  position: absolute;
  top: 100%;
  right: 0;
  z-index: 50;
  min-width: 200px;
  background: var(--surface);
  border: 1px solid var(--border-glow);
  border-radius: 8px;
  padding: 8px;
  margin-top: 4px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.team-filter__presets {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.team-filter__list label {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
  color: var(--text);
  cursor: pointer;
}

.team-filter__list label:hover {
  color: var(--active);
}

#team-filter-badge:not(:empty) {
  background: var(--active);
  color: var(--bg);
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 8px;
  margin-left: 4px;
}
```

- [ ] **Step 3: Implement team filter logic in renderer.js**

Add filter initialization and event handling:

```javascript
function initTeamFilter() {
  const btn = document.getElementById("team-filter-btn");
  const dropdown = document.getElementById("team-filter-dropdown");
  const list = document.getElementById("team-filter-list");
  const badge = document.getElementById("team-filter-badge");
  if (!btn || !dropdown) return;

  // Toggle dropdown
  btn.addEventListener("click", () => {
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
      label.appendChild(document.createTextNode(` ${team.name || teamId}`));
      list.appendChild(label);
    }
  }

  function _onFilterChange() {
    // Update badge
    const total = Object.keys(TEAMS).length;
    const visible = getVisibleTeamIds().length;
    badge.textContent = visible < total ? `${visible}/${total}` : "";
    // Rebuild layout with only visible teams
    rebuildLayout();
    resize();
  }
}
```

- [ ] **Step 4: Integrate filter with rebuildLayout()**

In `rebuildLayout()`, filter out hidden teams before computing the grid:

```javascript
function rebuildLayout() {
  const teams = TEAMS;
  const allTeamIds = computeTeamOrder(teams, PIPELINE_STAGES, STAGE_TO_TEAM);
  // Filter out hidden teams
  layoutTeamOrder = allTeamIds.filter(id => !isTeamHidden(id));

  const visibleCount = layoutTeamOrder.length || 1;
  const grid = computeGrid(visibleCount);
  // ... rest unchanged ...
}
```

- [ ] **Step 5: Call initTeamFilter() from init()**

In the main `init()` function, after config loads:

```javascript
initTeamFilter();
```

- [ ] **Step 6: Verify team filter**

Test:
- Click "Teams" button → dropdown appears with checkboxes per team
- Uncheck a team → room disappears, grid recomputes to fill gap
- Badge shows "3/4" when one team hidden
- "Show All" restores all teams
- "Pipeline Only" hides non-pipeline teams
- Hidden teams still receive events (check event log)

- [ ] **Step 7: Commit**

```bash
git add src/pixelpulse/static/modules/renderer.js src/pixelpulse/static/index.html src/pixelpulse/static/dashboard.css
git commit -m "feat: team filter dropdown with presets and dynamic grid recomputation"
```

---

### Task 11: Update Keyboard Help Dialog

**Files:**
- Modify: `src/pixelpulse/static/index.html` (keyboard help dialog content)

- [ ] **Step 1: Update keyboard help to reflect new shortcuts**

Find the `<dialog id="keyboard-help">` in `index.html` and update the shortcut list:

```html
<table class="keyboard-help__table">
  <tr><td><kbd>Space</kbd></td><td>Start/stop demo</td></tr>
  <tr><td><kbd>F</kbd></td><td>Toggle flow connectors</td></tr>
  <tr><td><kbd>+</kbd> / <kbd>-</kbd></td><td>Zoom in/out</td></tr>
  <tr><td><kbd>1</kbd>–<kbd>9</kbd></td><td>Focus room by position</td></tr>
  <tr><td><kbd>0</kbd></td><td>Return to overview</td></tr>
  <tr><td><kbd>Esc</kbd></td><td>Exit focus mode</td></tr>
  <tr><td><kbd>?</kbd></td><td>This help</td></tr>
</table>
```

- [ ] **Step 2: Commit**

```bash
git add src/pixelpulse/static/index.html
git commit -m "docs: update keyboard help dialog with dynamic canvas shortcuts"
```

---

### Task 12: Compact Overflow Mode

**Files:**
- Modify: `src/pixelpulse/static/modules/renderer.js` (buildRoomLayout, agent rendering)

- [ ] **Step 1: Handle overflow agents in compact mode**

In `buildRoomLayout()`, when `roomSizing === 'compact'` and `agents.length > 6`, only create full desk setups for the first 6 agents. Overflow agents get head icons:

```javascript
function buildRoomLayout(team, teamId, roomCols, roomRows) {
  const agents = team.agents;
  const items = [];
  const sizingMode = Settings.get('roomSizing') || 'uniform';

  // In compact mode, max 6 agents get full desk treatment
  const maxFullDesks = sizingMode === 'compact' ? 6 : agents.length;
  const deskAgents = agents.slice(0, maxFullDesks);
  const overflowAgents = agents.slice(maxFullDesks);

  // ... existing desk layout code using deskAgents instead of agents ...
  const cols = Math.min(deskAgents.length, 2);
  const rows = Math.ceil(deskAgents.length / 2);
  // ... (same centering math) ...

  for (let i = 0; i < deskAgents.length; i++) {
    // ... existing agent/desk/monitor push logic ...
  }

  // Overflow agents: small head icons along bottom edge
  if (overflowAgents.length > 0) {
    const iconSpacing = 1.2;
    const startX = (roomCols - overflowAgents.length * iconSpacing) / 2;
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

    // +N badge
    items.push({
      type: "overflow-badge",
      col: startX + overflowAgents.length * iconSpacing,
      row: iconY,
      count: overflowAgents.length,
    });
  }

  // ... decorations unchanged ...
}
```

- [ ] **Step 2: Draw overflow agent icons and badge**

In the drawable rendering switch in `render()`, add cases:

```javascript
case "overflow-agent": {
  // Small 8x8 pixel head icon
  const agent = getAgent(d.agent);
  const style = TEAM_STYLES[d.teamId] || TEAM_STYLES.research;
  const iconSize = 8 * zoom;

  // Head circle
  ctx.fillStyle = agent?.status === "active" ? style.accent : "#475569";
  ctx.beginPath();
  ctx.arc(d.x + iconSize / 2, d.y + iconSize / 2, iconSize / 2, 0, Math.PI * 2);
  ctx.fill();

  // Glow if active
  if (agent?.status === "active") {
    ctx.save();
    ctx.shadowColor = style.accent;
    ctx.shadowBlur = 6 * zoom;
    ctx.beginPath();
    ctx.arc(d.x + iconSize / 2, d.y + iconSize / 2, iconSize / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
  break;
}

case "overflow-badge": {
  const fontSize = Math.max(7, Math.round(7 * zoom * 0.5));
  ctx.font = `${fontSize}px "JetBrains Mono", monospace`;
  ctx.fillStyle = "#94a3b8";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(`+${d.count}`, d.x, d.y + 4 * zoom);
  break;
}
```

- [ ] **Step 3: Active overflow agent pop-up**

When an overflow agent becomes active, swap it with an idle seated agent:

```javascript
// In buildRoomLayout, before slicing agents:
if (sizingMode === 'compact' && agents.length > 6) {
  // Sort so active agents get priority for desk positions
  const sorted = [...agents].sort((a, b) => {
    const aAgent = getAgent(a);
    const bAgent = getAgent(b);
    const aActive = aAgent?.status === "active" ? 0 : 1;
    const bActive = bAgent?.status === "active" ? 0 : 1;
    return aActive - bActive;
  });
  // Use sorted order for desk assignment
  const deskAgents = sorted.slice(0, maxFullDesks);
  const overflowAgents = sorted.slice(maxFullDesks);
  // ... rest of layout with these arrays ...
}
```

- [ ] **Step 4: Verify compact mode**

Test with a team that has 10 agents:
- Switch to "Compact Overflow" in settings
- First 6 agents have full desks
- Remaining 4 show as small head icons along bottom
- "+4" badge is visible
- When an overflow agent becomes active, it swaps into a desk position

- [ ] **Step 5: Commit**

```bash
git add src/pixelpulse/static/modules/renderer.js
git commit -m "feat: compact overflow mode — 6 max desks, overflow as head icons with +N badge"
```

---

### Task 13: TEAM_STYLES Dynamic Registration

**Files:**
- Modify: `src/pixelpulse/static/modules/renderer.js` (TEAM_STYLES object)

- [ ] **Step 1: Generate styles for unknown teams**

Currently `TEAM_STYLES` only has 4 entries. For dynamic team counts, generate colors for unknown teams:

```javascript
// Color palette for dynamic team generation
const DYNAMIC_COLORS = [
  { wall: "#0e4d64", floor1: "#0c1a2a", floor2: "#0f2236", accent: "#00d4ff" },
  { wall: "#4a1942", floor1: "#1a0c20", floor2: "#220f28", accent: "#ff6ec7" },
  { wall: "#14432d", floor1: "#0c1a10", floor2: "#0f2214", accent: "#39ff14" },
  { wall: "#4a3510", floor1: "#1a1408", floor2: "#22190a", accent: "#ffae00" },
  { wall: "#2a1a4a", floor1: "#120c1a", floor2: "#180f22", accent: "#aa88ff" },
  { wall: "#4a2a0e", floor1: "#1a120c", floor2: "#22180f", accent: "#ff8844" },
  { wall: "#0e4a4a", floor1: "#0c1a1a", floor2: "#0f2222", accent: "#44ffdd" },
  { wall: "#4a0e2a", floor1: "#1a0c12", floor2: "#220f18", accent: "#ff44aa" },
  { wall: "#3a3a10", floor1: "#18180c", floor2: "#20200f", accent: "#dddd44" },
  { wall: "#0e2a4a", floor1: "#0c121a", floor2: "#0f1822", accent: "#4488ff" },
];

function getTeamStyle(teamId) {
  if (TEAM_STYLES[teamId]) return TEAM_STYLES[teamId];

  // Generate deterministic style from team ID
  let hash = 0;
  for (let i = 0; i < teamId.length; i++) {
    hash = ((hash << 5) - hash) + teamId.charCodeAt(i);
    hash |= 0;
  }
  const idx = Math.abs(hash) % DYNAMIC_COLORS.length;
  const style = DYNAMIC_COLORS[idx];

  // Cache it
  TEAM_STYLES[teamId] = style;
  return style;
}
```

- [ ] **Step 2: Replace all TEAM_STYLES[teamId] lookups**

Replace all occurrences of `TEAM_STYLES[teamId]` with `getTeamStyle(teamId)` throughout renderer.js. Key locations:
- `drawRoom()` — floor colors, wall colors, accent
- `drawSpriteWithGlow()` — accent color
- `drawAgent()` — status colors
- `drawFlowConnectors()` — accent color
- `drawCollapsedBadge()` — accent color
- `drawMinimap()` — room fill color

- [ ] **Step 3: Update decoration mapping**

The `teamDecor` mapping in `buildRoomLayout` only covers 4 teams. Add a fallback:

```javascript
const teamDecor = {
  research: "whiteboard", design: "easel",
  commerce: "box", learning: "trophy",
};
const FALLBACK_DECORS = ["whiteboard", "easel", "box", "trophy", "plant"];
const decor = teamDecor[teamId] || FALLBACK_DECORS[Math.abs(hash) % FALLBACK_DECORS.length];
```

(Use the same hash from `getTeamStyle`.)

- [ ] **Step 4: Verify with 8-team config**

Modify the demo mode or create a test config with 8 teams. Verify:
- All 8 rooms get distinct colors
- Decorations appear in rooms without hardcoded mappings
- Grid computes as 3x3 (with 1 empty slot)

- [ ] **Step 5: Commit**

```bash
git add src/pixelpulse/static/modules/renderer.js
git commit -m "feat: dynamic team color generation for arbitrary team counts"
```

---

### Task 14: Integration Testing and Polish

**Files:**
- Modify: `src/pixelpulse/static/modules/renderer.js` (final adjustments)
- Modify: `src/pixelpulse/static/modules/demo.js` (multi-team demo scenarios)

- [ ] **Step 1: Add multi-team demo scenarios**

In `demo.js`, add an option to demo with varying team counts. After the existing demo events, add a helper that can initialize a simulated config with N teams:

```javascript
// At the end of the demo event sequence, optionally test with more teams:
// This is for manual testing only — triggered by a URL param like ?demo_teams=8
function _getDemoTeamCount() {
  const params = new URLSearchParams(window.location.search);
  return parseInt(params.get('demo_teams')) || 4;
}
```

Use this count when setting up demo teams in the demo config initialization.

- [ ] **Step 2: Manual testing matrix**

Run through each scenario from the spec (section 8):

| Scenario | Verify |
|----------|--------|
| `?demo_teams=1` | Single room, centered |
| `?demo_teams=4` | 2x2 grid, matches old layout |
| `?demo_teams=7` | 3x3 grid, 2 empty slots |
| `?demo_teams=15` | 4x4 grid, minimap visible |
| `?demo_teams=20` | 5x4 grid, smaller rooms if adaptive |
| Focus mode | Double-click zoom, ESC return |
| Collapse 3 rooms | Badges in place, others unchanged |
| Compact + 12 agents | 6 desks + 6 overflow icons |
| Flow connectors | F key toggle, dashed lines |
| Team filter | Hide/show teams, grid reflows |
| Settings: Uniform | All rooms same size |
| Settings: Adaptive | Rooms vary by agent count |
| Settings: Compact | Fixed 9-tile with overflow |

- [ ] **Step 3: Fix any visual regressions**

Address any spacing, alignment, or rendering issues found during testing. Common issues:
- Room labels overlapping at small zoom
- Minimap viewport rectangle accuracy
- Orchestrator zone positioning with >2 rows
- Roaming bounds at non-9x9 room sizes

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: dynamic canvas — complete implementation with all progressive disclosure features"
```

---

## Summary

| Task | Feature | Priority |
|------|---------|----------|
| 1 | Settings foundation | Setup |
| 2 | Dynamic grid computation | Core |
| 3 | Parameterized room layout + roaming | Core |
| 4 | Room labels + orchestrator zone | Core |
| 5 | Dynamic canvas state fields | Core |
| 6 | Focus mode | P1 (Must Have) |
| 7 | Collapsible rooms | P2 |
| 8 | Flow connectors | P2 |
| 9 | Minimap | P3 |
| 10 | Team filter | P4 |
| 11 | Keyboard help update | Polish |
| 12 | Compact overflow mode | P2 |
| 13 | Dynamic team styles | Core |
| 14 | Integration testing | Verification |

**Total: 14 tasks, ~60 steps, estimated 14 commits.**

Tasks 1-5 are the critical foundation. Task 6 is the must-have feature. Tasks 7-13 add progressive disclosure. Task 14 validates everything.
