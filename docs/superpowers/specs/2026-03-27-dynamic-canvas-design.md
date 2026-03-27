# Dynamic Canvas Design Spec

**Date:** 2026-03-27
**Status:** Approved
**Scope:** PixelPulse dashboard canvas — dynamic layout engine for arbitrary team/agent counts

## Problem

The current canvas is hardcoded for exactly 4 teams in a 2x2 grid with 9x9 tile rooms. Teams beyond 4 are ignored. Rooms with 8+ agents overflow their boundaries. This makes PixelPulse unusable as a general-purpose library for arbitrary multi-agent systems.

## Goals

- Handle 1 to 20+ teams with graceful degradation
- Handle 1 to 100+ agents across teams
- Maintain the pixel-art charm at normal scales (1-8 teams)
- Provide progressive disclosure features for large-scale systems
- All layout parameters configurable via settings

## Non-Goals

- Creator/drag-drop mode (separate future spec)
- 3D or isometric views
- Real-time layout reconfiguration (hot-adding teams during a run)

---

## 1. Dynamic Grid Layout Engine

### Grid Computation

Replace `ROOMS_PER_ROW = 2` with computed layout:

```javascript
function computeGrid(teamCount) {
    const cols = Math.ceil(Math.sqrt(teamCount));
    const rows = Math.ceil(teamCount / cols);
    return { cols, rows };
}
```

Examples:
| Teams | Grid | Layout |
|-------|------|--------|
| 1 | 1x1 | Single room |
| 2 | 2x1 | Side by side |
| 3 | 2x2 | L-shape (1 empty) |
| 4 | 2x2 | Full grid |
| 6 | 3x2 | 3 columns |
| 9 | 3x3 | Square |
| 12 | 4x3 | 4 columns |
| 20 | 5x4 | 5 columns |

### Pipeline-Aware Ordering

When a `pipeline` config array exists:
1. Rooms are placed in pipeline order (stage 1 at grid position 0, stage 2 at position 1, etc.)
2. Non-pipeline teams fill remaining slots after pipeline teams
3. Spatial position implies flow direction — no arrows needed by default

When no pipeline config exists, rooms are placed in the order provided in the `teams` config.

### Content Bounds

`CONTENT_TILES_W` and `CONTENT_TILES_H` are computed dynamically:

```javascript
const CONTENT_TILES_W = PAD_LEFT + cols * roomCols + (cols - 1) * ROOM_GAP + PAD_RIGHT;
const CONTENT_TILES_H = PAD_TOP + rows * roomRows + (rows - 1) * ROOM_GAP + orchestratorHeight + PAD_BOTTOM;
```

The existing `baseZoom` auto-fit logic in `resize()` already handles this — it divides canvas size by content size.

### Orchestrator Zone

The orchestrator is a special room type:
- **1 row of teams**: orchestrator placed below as a half-width room
- **2+ rows**: orchestrator gets a dedicated row between the first row and the rest (current behavior, but now computed)
- If no orchestrator is configured, the zone is omitted and teams fill the full grid

---

## 2. Adaptive Room Rendering

### Room Sizing Modes (User Setting)

Exposed in settings panel as **"Room sizing"** dropdown with 3 options:

#### Uniform (Default)

All rooms share the same size, computed from the team with the most agents:

```javascript
function uniformRoomSize(teams) {
    const maxAgents = Math.max(...Object.values(teams).map(t => t.agents.length));
    if (maxAgents <= 2) return 7;
    if (maxAgents <= 4) return 9;
    if (maxAgents <= 8) return 12;
    return 14;
}
```

#### Adaptive

Each room gets its own size based on its agent count:

```javascript
function adaptiveRoomSize(agentCount) {
    if (agentCount <= 2) return 7;   // cozy
    if (agentCount <= 4) return 9;   // standard
    if (agentCount <= 8) return 12;  // large
    return 14;                        // extra large
}
```

Grid alignment: rooms in the same row use the tallest room's height. Rooms in the same column use the widest room's width. This keeps the grid aligned while allowing size variation.

#### Compact Overflow

Fixed 9-tile rooms. Max 6 agents get full desk+monitor+chair treatment. Beyond 6:

- Extra agents render as small pixel-art head icons (8x8 px) along the room's bottom edge
- A "+N" badge shows the overflow count
- Clicking the badge shows agent names in a tooltip
- Active overflow agents still get glow effects and status color indicators
- When an overflow agent becomes active, it "pops up" to a full desk position temporarily (swapping with an idle seated agent)

### Desk Layout Within Rooms

Same pattern as current: 2 desks per row, centered in room. Room boundary grows to fit.

Furniture (plants, bookshelves, whiteboards) scales proportionally:
- 7-tile rooms: 1-2 furniture items
- 9-tile rooms: 3-4 items (current)
- 12-tile rooms: 5-6 items
- 14-tile rooms: 6-8 items

Furniture placement uses the existing random-seed approach but respects the larger walkable area.

### Roaming

Idle agents roam within their own room boundaries. The walkable area and collision grid recalculate when room dimensions change. No changes to pathfinding logic — just larger bounds.

---

## 3. Flow Connectors (Optional Overlay)

### Design

Subtle dashed lines connecting rooms in pipeline order. Drawn as a canvas overlay on top of room rendering.

- **Style**: 1px dashed line, team's highlight color at 30% opacity
- **Path routing**: straight lines between room centers, with rounded corners at bends
- **Multi-directional**: connectors follow grid position order, not forced left-to-right
- **Animated**: optional slow pulse animation when a stage transition occurs (data flowing)

### Toggle

- **Setting**: "Show flow connectors" checkbox in settings panel (default: OFF)
- **Keyboard shortcut**: `F` key toggles connectors
- Connectors only render when a `pipeline` config exists

### No connectors when

- No pipeline config provided
- Setting is OFF
- Only 1 team exists

---

## 4. Progressive Disclosure

### 4.1 Focus Mode (Priority 1 — Must Have)

- **Trigger**: double-click a room
- **Effect**: canvas smoothly zooms to fill the viewport with just that room. Other rooms fade to 20% opacity.
- **Exit**: press ESC, or click outside the focused room, or double-click the room again
- **Keyboard**: number keys 1-9 focus rooms by position. `0` returns to overview.
- **During focus**: all events for that team are highlighted in the event log sidebar

### 4.2 Collapsible Rooms (Priority 2)

- **Trigger**: click the room header (team name label)
- **Effect**: room collapses to a compact badge showing: team icon, team name, agent count, active agent indicator (pulsing dot if any agent is working)
- **Collapsed size**: 3x1 tiles (fits the badge)
- **Grid reflow**: collapsed rooms free up space; adjacent rooms don't move (maintains spatial stability). The collapsed badge stays in its grid slot.
- **Persistence**: collapse state persists in localStorage

### 4.3 Minimap (Priority 3)

- **Position**: bottom-right corner, 120x80px semi-transparent overlay
- **Content**: simplified room rectangles (filled with team color), current viewport shown as a white rectangle outline
- **Interaction**: click on minimap to pan the main canvas to that position
- **Auto-hide**: only visible when content exceeds viewport (i.e., user would need to pan/zoom). Hidden when everything fits on screen.

### 4.4 Team Filter (Priority 4)

- **Location**: topbar, next to existing controls
- **UI**: dropdown with checkboxes per team, plus "Show all" and "Pipeline only" presets
- **Effect**: hidden teams' rooms are removed from the grid (grid recomputes to fill gaps). Hidden teams still receive events — they're just not rendered.
- **Badge**: filter button shows a count badge when teams are hidden (e.g., "Teams (4/7)")

---

## 5. Settings Integration

New settings added to the existing settings panel:

| Setting | Type | Default | Options |
|---------|------|---------|---------|
| Room sizing | dropdown | Uniform | Uniform, Adaptive, Compact overflow |
| Show flow connectors | checkbox | OFF | ON/OFF |
| Orchestrator visible | checkbox | ON | ON/OFF |

All settings persist in localStorage under the existing `pixelpulse-settings` key.

Settings changes trigger a full layout recomputation (`rebuildLayout()`) followed by a smooth transition animation (rooms slide to new positions over 300ms).

---

## 6. Config API Changes

### Python SDK

No changes to the `PixelPulse` constructor API. The existing config already supports arbitrary teams and agents:

```python
pp = PixelPulse(
    agents={"a1": {"team": "t1"}, "a2": {"team": "t1"}, ...},  # any count
    teams={"t1": {...}, "t2": {...}, ...},                       # any count
    pipeline=["t1", "t2", "t3"],                                 # optional
)
```

### WebSocket Config Message

The `/ws/events` connection already sends a `config` message on connect with full team/agent data. No protocol changes needed — the frontend just needs to handle arbitrary counts instead of assuming 4 teams.

### Server-Side

`GET /config` endpoint already returns the full config. No changes needed.

---

## 7. File Changes

### Modified Files

| File | Change |
|------|--------|
| `static/modules/renderer.js` | Replace hardcoded grid constants with `computeGrid()`. Extract room sizing into configurable functions. Add focus mode, collapse, minimap rendering. Add flow connector overlay. |
| `static/modules/state.js` | Add `focusedRoom`, `collapsedRooms`, `hiddenTeams` to state. Add settings for room sizing and connectors. |
| `static/index.html` | Add minimap canvas element. Add team filter dropdown to topbar. Add new settings controls. |
| `static/dashboard.css` | Minimap styles, collapsed room badge styles, team filter dropdown styles. |

### New Files

None — all changes are within existing files. The renderer.js refactor should extract layout computation into a separate section at the top of the file but not a new file (keeps the module count low for a frontend library).

---

## 8. Testing Strategy

### Manual Testing Matrix

| Scenario | Expected |
|----------|----------|
| 1 team, 1 agent | Single room, centered |
| 4 teams, 8 agents | 2x2 grid (matches current) |
| 7 teams, 20 agents | 3x3 grid with 2 empty slots |
| 15 teams, 50 agents | 4x4 grid, minimap visible, zoom out |
| 20 teams, 100 agents | 5x4 grid, rooms smaller, minimap + filter essential |
| 1 team, 12 agents (compact) | Single room, 6 desks + 6 overflow icons |
| Pipeline with 5 stages | Rooms in pipeline order, connectors available |
| Focus mode | Double-click zooms, ESC returns |
| Collapse 3 of 6 rooms | Collapsed badges in grid slots, expanded rooms unchanged |

### Automated Tests

- `test_layout.py`: unit tests for `computeGrid()` at various team counts
- `test_room_sizing.py`: tests for all 3 sizing modes with edge cases
- Frontend: extend existing examples to test with 1, 4, 8, 15 teams

---

## 9. Migration / Backward Compatibility

- **Existing configs with 4 teams**: render identically to current (2x2 grid, 9x9 rooms)
- **No API changes**: all changes are frontend-only
- **Settings default to current behavior**: uniform sizing, no connectors, no collapsed rooms
- **Zero-config upgrade**: users see the same dashboard after updating, with new capabilities available in settings
