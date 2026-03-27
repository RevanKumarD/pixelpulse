# PixelPulse Claude Code Plugin — Design Spec

> **Date:** 2026-03-27
> **Status:** Approved
> **Scope:** Claude Code plugin + MCP server + VS Code extension strategy
> **Vision:** "Observability for AI developers building software"

---

## 1. Problem Statement

Today, when Claude Code runs a complex session — spawning subagents, making parallel tool calls, spending tokens — the developer has no visibility into what's happening. The terminal shows one message at a time. There's no way to see:

- Which subagents are active and what they're doing
- How much the session is costing in real-time
- The tree of parallel agents and their relationships
- Tool call patterns and bottlenecks
- Whether a subagent is stuck or making progress

Existing solutions (`disler/claude-code-hooks-multi-agent-observability`, 1.3k stars) provide basic event tables. But nobody provides a **visually rich, pixel-art dashboard** where agents walk around office rooms, show speech bubbles with their reasoning, and pass glowing message particles between teams — and where **Claude itself can query its own performance metrics**.

## 2. Solution Overview

A Claude Code plugin that:

1. **Auto-registers hooks** — No manual `.claude/settings.json` editing. Install the plugin and it works.
2. **Auto-starts the PixelPulse server** — On `SessionStart`, the plugin ensures a PixelPulse dashboard is running.
3. **Provides MCP tools** — Claude can query its own session metrics (cost, tool usage, subagent tree).
4. **Includes a skill** — Claude knows it's being observed and can report on its own efficiency.
5. **Pixel-art dashboard** — The same beautiful dashboard that already supports 8 frameworks.

## 3. Architecture

### 3.1 Plugin Directory Structure

```
plugins/claude-code/                    # Lives inside PixelPulse repo
├── .claude-plugin/
│   └── plugin.json                     # Manifest
├── hooks/
│   └── hooks.json                      # Auto-registered lifecycle hooks
├── scripts/
│   ├── hook_handler.py                 # UV single-file script — handles all hook events
│   └── ensure_server.py               # UV single-file script — starts PP server if needed
├── skills/
│   └── pixelpulse-status/
│       └── SKILL.md                    # Model-invoked skill for session awareness
├── agents/
│   └── session-analyzer.md             # Agent for session pattern analysis
├── .mcp.json                           # MCP server configuration
├── mcp-server/
│   ├── __init__.py
│   └── server.py                       # MCP server exposing PP data as tools
└── README.md                           # Plugin-specific docs
```

### 3.2 Data Flow

```
Claude Code Session
    │
    ├─ SessionStart ────┐
    ├─ PreToolUse ──────┤
    ├─ PostToolUse ─────┤
    ├─ SubagentStart ───┤  hooks.json (auto-registered)
    ├─ SubagentStop ────┤       │
    ├─ Stop ────────────┤       ▼
    └─ SessionEnd ──────┘  hook_handler.py
                               │
                          HTTP POST (JSON)
                               │
                               ▼
                     PixelPulse Server (:8765)
                        /hooks/claude-code
                               │
                          ┌────┴────┐
                          ▼         ▼
                      EventBus   SQLite (v2)
                          │
                    ┌─────┼─────┐
                    ▼     ▼     ▼
               WebSocket  HTTP  MCP Server
               (browser)  API   (tools for Claude)
                    │           │
                    ▼           ▼
              Pixel-art    Claude queries:
              Dashboard    "How much have I spent?"
                           "Show my subagent tree"
```

### 3.3 Hook Handler Design

A single `hook_handler.py` script handles ALL hook events. It uses the `uv` single-file script pattern (inline dependency declarations) so there's no venv setup. This is the dominant pattern in the Claude Code plugin ecosystem.

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
```

The handler:
1. Reads JSON from stdin (Claude Code hook payload)
2. Enriches with timing data (tracks tool start times in a temp file)
3. POSTs to `http://localhost:{port}/hooks/claude-code`
4. Returns `{"continue": true}` on stdout

For `SessionStart`, it also calls `ensure_server.py` to start the PixelPulse server if not already running.

### 3.4 Server Lifecycle Management

`ensure_server.py` handles:
1. Check if PixelPulse is already running (`GET /api/health`)
2. If not, start it as a background subprocess: `pixelpulse serve --port 8765`
3. Wait for health check to pass (up to 10s)
4. Optionally open browser (based on `userConfig.auto_open_browser`)

Server shutdown options:
- **Default**: Server keeps running after session ends (for reviewing results)
- **Auto-stop**: Optional `userConfig.auto_stop` to kill on `SessionEnd`

## 4. Plugin Manifest

```json
{
  "name": "pixelpulse",
  "version": "0.3.0",
  "description": "Pixel-art observability dashboard — watch your Claude Code session live with animated agents, speech bubbles, cost tracking, and subagent visualization",
  "author": {
    "name": "RevanKumarD",
    "url": "https://github.com/RevanKumarD"
  },
  "homepage": "https://github.com/RevanKumarD/pixelpulse",
  "repository": "https://github.com/RevanKumarD/pixelpulse",
  "license": "Apache-2.0",
  "keywords": [
    "observability",
    "dashboard",
    "pixel-art",
    "monitoring",
    "agents",
    "subagents",
    "cost-tracking",
    "multi-agent"
  ],
  "userConfig": {
    "port": {
      "description": "Dashboard port (default: 8765)",
      "sensitive": false
    },
    "auto_open_browser": {
      "description": "Open dashboard in browser on session start (default: true)",
      "sensitive": false
    },
    "auto_stop_server": {
      "description": "Stop dashboard server when session ends (default: false)",
      "sensitive": false
    }
  }
}
```

## 5. Hooks Configuration

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uv run ${CLAUDE_PLUGIN_ROOT}/scripts/hook_handler.py",
            "timeout": 15000,
            "statusMessage": "Starting PixelPulse dashboard..."
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uv run ${CLAUDE_PLUGIN_ROOT}/scripts/hook_handler.py",
            "timeout": 5000
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uv run ${CLAUDE_PLUGIN_ROOT}/scripts/hook_handler.py",
            "timeout": 5000
          }
        ]
      }
    ],
    "SubagentStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uv run ${CLAUDE_PLUGIN_ROOT}/scripts/hook_handler.py",
            "timeout": 5000
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uv run ${CLAUDE_PLUGIN_ROOT}/scripts/hook_handler.py",
            "timeout": 5000
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uv run ${CLAUDE_PLUGIN_ROOT}/scripts/hook_handler.py",
            "timeout": 5000
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "uv run ${CLAUDE_PLUGIN_ROOT}/scripts/hook_handler.py",
            "timeout": 10000,
            "statusMessage": "Saving PixelPulse session..."
          }
        ]
      }
    ]
  }
}
```

## 6. MCP Server

### 6.1 Configuration (`.mcp.json`)

```json
{
  "mcpServers": {
    "pixelpulse": {
      "command": "uv",
      "args": ["run", "${CLAUDE_PLUGIN_ROOT}/mcp-server/server.py"],
      "env": {
        "PIXELPULSE_PORT": "8765",
        "PIXELPULSE_DATA_DIR": "${CLAUDE_PLUGIN_DATA}"
      }
    }
  }
}
```

### 6.2 Tools Exposed

| Tool | Description | Returns |
|------|-------------|---------|
| `pixelpulse_session_stats` | Current session metrics | `{tool_calls: int, tokens_in: int, tokens_out: int, cost: float, duration_s: float, subagents_spawned: int}` |
| `pixelpulse_cost_breakdown` | Per-model token costs | `[{model: str, tokens_in: int, tokens_out: int, cost: float, calls: int}]` |
| `pixelpulse_subagent_tree` | Tree of all spawned subagents | `{id: str, type: str, description: str, status: str, children: [...]}` |
| `pixelpulse_tool_summary` | Tool usage frequency and timing | `[{tool: str, count: int, avg_duration_ms: int, total_duration_ms: int}]` |
| `pixelpulse_recent_events` | Last N events from the session | `[{type: str, timestamp: str, agent: str, payload: dict}]` |
| `pixelpulse_dashboard_url` | URL of the running dashboard | `{url: str, status: str}` |

### 6.3 Implementation

The MCP server is a lightweight Python process that:
1. Connects to the PixelPulse server's HTTP API (`/api/events`, `/api/config`)
2. Aggregates event data into the tool response shapes above
3. Uses the MCP Python SDK (`mcp` package) to expose tools

The server reads from the same event bus that powers the dashboard — no separate data store needed for v1. For v2, it can read from SQLite for historical queries.

## 7. Skill Definition

### `skills/pixelpulse-status/SKILL.md`

```markdown
---
name: pixelpulse-status
description: Use when the user asks about session progress, token usage, costs,
  tool patterns, subagent activity, or session efficiency. Also use when reflecting
  on what work has been done in the current session.
---

# PixelPulse Session Status

You have access to real-time observability data about your current session via the
pixelpulse MCP tools. Use them to answer questions about:

- **Cost**: "How much have I spent?" → use `pixelpulse_session_stats` or `pixelpulse_cost_breakdown`
- **Activity**: "What tools have I used most?" → use `pixelpulse_tool_summary`
- **Subagents**: "What are my subagents doing?" → use `pixelpulse_subagent_tree`
- **Events**: "What happened recently?" → use `pixelpulse_recent_events`
- **Dashboard**: "Where can I see the dashboard?" → use `pixelpulse_dashboard_url`

When reporting costs, always include both token counts and dollar amounts.
When reporting subagent status, include the agent type and current status.
```

## 8. Session Analyzer Agent

### `agents/session-analyzer.md`

```markdown
---
name: session-analyzer
description: Analyzes Claude Code session patterns for efficiency insights.
  Use when the user wants to understand their session's performance profile.
tools:
  - pixelpulse_session_stats
  - pixelpulse_cost_breakdown
  - pixelpulse_tool_summary
  - pixelpulse_subagent_tree
  - pixelpulse_recent_events
---

You are a session efficiency analyst. When invoked, use the pixelpulse MCP tools
to gather data about the current session, then provide a brief analysis covering:

1. **Cost efficiency**: Total spend, cost per tool call, most expensive operations
2. **Tool patterns**: Most-used tools, average durations, potential bottlenecks
3. **Subagent utilization**: How many subagents, parallelism, idle time
4. **Recommendations**: Concrete suggestions for improving session efficiency

Keep the analysis under 200 words. Focus on actionable insights, not raw data.
```

## 9. VS Code Extension (v2 — Planned)

Based on the VS Code architecture research, the extension will:

### 9.1 Architecture Decision: Option C (Spawn Python Subprocess)

The extension spawns the PixelPulse server as a Python subprocess and displays the dashboard in a VS Code Webview panel. This was chosen over:
- Option A (load localhost in webview) — blocked by VS Code's strict CSP
- Option B (bundle static assets) — duplicates assets, complex build

### 9.2 Extension Components

```
vscode-pixelpulse/
├── package.json              # Extension manifest
├── src/
│   ├── extension.ts          # Activation, command registration
│   ├── server-manager.ts     # Start/stop PixelPulse Python server
│   ├── webview-provider.ts   # Dashboard webview panel
│   └── status-bar.ts         # Status bar item (cost counter)
├── media/
│   └── icon.png              # Extension icon (pixel art)
└── README.md
```

### 9.3 UX Flow

1. User opens VS Code with PixelPulse extension installed
2. Extension checks for Python + `pixelpulse` package
3. On activation (or when user runs "PixelPulse: Open Dashboard"):
   - Detects existing PixelPulse server via `GET /api/health`
   - If not running, spawns `pixelpulse serve --port 8765` (`windowsHide: true`)
   - Opens Webview panel with embedded dashboard (CSP allows `frame-src http://localhost:8765`)
4. Status bar shows live cost counter and agent activity
5. When Claude Code runs in the terminal, events flow to the same dashboard

### 9.4 Key Technical Decisions

- **CSP**: Relax to `frame-src http://localhost:*` for the PixelPulse webview only
- **Python detection**: Use VS Code Python extension API to find interpreter
- **Windows**: `windowsHide: true` on `child_process.spawn` to prevent console flash
- **Remote**: Support VS Code Remote by checking if port is forwarded

### 9.5 Marketplace Positioning

- Category: "AI / Machine Learning" or "Visualization"
- Tagline: "Watch your AI agents work — pixel-art observability in your IDE"
- Prerequisites documented: Python 3.10+, `pip install pixelpulse`

## 10. Competitive Differentiation

| Feature | PixelPulse Plugin | disler/observability | claude-hud | AgentOps |
|---------|-------------------|---------------------|------------|----------|
| Pixel-art dashboard | Yes | No (Vue table) | No (terminal) | No (web table) |
| Auto-hook registration | Yes (plugin) | No (manual) | Yes (hooks) | N/A |
| MCP self-awareness | Yes | No | No | No |
| Framework-agnostic | Yes (8 frameworks) | No (CC only) | No (CC only) | Yes (4 frameworks) |
| Zero-config | Yes | No | Yes | No |
| VS Code extension | Planned v2 | No | No | No |
| Cost tracking | Yes | Yes | Yes | Yes |
| Subagent tree | Yes | Basic | Basic | No |
| Session replay | Planned v2 | No | No | Yes |
| Open source | Yes (Apache-2.0) | Yes | Yes | Partial |

## 11. Implementation Phases

### Phase 1: Core Plugin (v0.3.0) — THIS SPEC

- [ ] Plugin manifest and directory structure
- [ ] Hook handler script (all 7 events)
- [ ] Server lifecycle management (auto-start/stop)
- [ ] MCP server with 6 tools
- [ ] Skill definition
- [ ] Session analyzer agent
- [ ] Plugin README
- [ ] Tests: hook handler unit tests, MCP server integration tests
- [ ] Example: install and run walkthrough

### Phase 2: Enhanced Monitoring (v0.4.0)

- [ ] SQLite session persistence in `${CLAUDE_PLUGIN_DATA}/sessions.db`
- [ ] Session replay via MCP tool (`pixelpulse_replay_session`)
- [ ] Git commit tracking (PostToolUse matcher for Write/Edit)
- [ ] Decision tree visualization (why Claude chose tool X)
- [ ] Cost alerting via hook (exit code 2 when threshold exceeded)
- [ ] Multi-session comparison dashboard view
- [ ] StatusLine HUD integration (summary stats in terminal)

### Phase 3: VS Code Extension (v0.5.0)

- [ ] Extension scaffolding (TypeScript)
- [ ] Python server lifecycle management
- [ ] Webview panel with embedded dashboard
- [ ] Status bar cost counter
- [ ] Python interpreter detection
- [ ] VS Code Marketplace submission

### Phase 4: Agent Dev Mode (v1.0.0) — "Observability for AI Developers"

- [ ] Reasoning trace visualization (thinking → decision → action tree)
- [ ] File change timeline (which files changed, when, by which agent)
- [ ] Commit graph overlay (link dashboard events to git commits)
- [ ] Session comparison ("this session vs last session")
- [ ] Team analytics (multi-developer session aggregation)
- [ ] Hosted cloud option (optional, privacy-first)
- [ ] Claude Code marketplace submission

## 12. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `uv` not installed on user's system | Hook scripts fail silently | Hook scripts use shebang `#!/usr/bin/env -S uv run --script` with `python3` fallback. Scripts check for `uv` first; if absent, use `python3 -c "import httpx"` path. Document `uv` as recommended, `python3 + pip install httpx` as alternative. |
| PixelPulse server fails to start | No dashboard, hooks still fire | Graceful degradation — hooks continue, events buffered to temp file |
| Hook latency (5s timeout) | Claude Code feels slow | Use async HTTP POST with `httpx`; don't wait for response |
| MCP server crashes | Claude loses observability tools | MCP server is stateless — auto-restarts on next tool call |
| Port conflict (8765 in use) | Server won't start | Check `userConfig.port`, try fallback ports 8766-8770 |
| VS Code CSP blocks dashboard | Blank webview | Use `frame-src http://localhost:*` CSP override |
| Plugin marketplace not yet stable | Can't distribute easily | Support `--plugin-dir` for direct install; publish on custom marketplace |

## 13. Testing Strategy

### Unit Tests
- Hook handler: parse all 7 event types correctly
- Server manager: start/stop/health-check logic
- MCP server: each tool returns correct shape
- Cost calculation: token → dollar conversion

### Integration Tests
- Hook handler → HTTP POST → PixelPulse server → `/api/events` (existing pattern)
- MCP server → PixelPulse API → aggregated response

### Functional Tests
- Full plugin flow: SessionStart → tool calls → SubagentStart/Stop → Stop → SessionEnd
- All events appear on dashboard with correct types and payloads

### Manual Validation
- Install plugin via `--plugin-dir`, run Claude Code session, verify dashboard works
- Test MCP tools from Claude Code: "How much have I spent?"
- Test on Windows, macOS, Linux

## 14. File Inventory

New files to create:

| File | Purpose | Lines (est.) |
|------|---------|-------------|
| `plugins/claude-code/.claude-plugin/plugin.json` | Manifest | 30 |
| `plugins/claude-code/hooks/hooks.json` | Hook registration | 80 |
| `plugins/claude-code/scripts/hook_handler.py` | Hook event handler | 150 |
| `plugins/claude-code/scripts/ensure_server.py` | Server lifecycle | 80 |
| `plugins/claude-code/skills/pixelpulse-status/SKILL.md` | Skill definition | 25 |
| `plugins/claude-code/agents/session-analyzer.md` | Agent definition | 25 |
| `plugins/claude-code/.mcp.json` | MCP server config | 15 |
| `plugins/claude-code/mcp-server/__init__.py` | Package init | 1 |
| `plugins/claude-code/mcp-server/server.py` | MCP server implementation | 200 |
| `plugins/claude-code/README.md` | Plugin documentation | 100 |
| `tests/plugin/test_hook_handler.py` | Hook handler tests | 150 |
| `tests/plugin/test_mcp_server.py` | MCP server tests | 150 |
| `tests/plugin/test_server_manager.py` | Server lifecycle tests | 80 |

**Total: ~1,086 lines of new code across 13 files.**

Existing files to modify:

| File | Change |
|------|--------|
| `README.md` | Add Claude Code plugin section to Framework Adapters table |
| `pyproject.toml` | Add `pixelpulse` CLI entry point for `pixelpulse serve` command |
| `src/pixelpulse/cli.py` | Add `serve` CLI command (if not exists) |
