# PixelPulse Claude Code Plugin

Watch your Claude Code session live with an animated pixel-art dashboard.

## What You Get

- **Auto-start dashboard** — PixelPulse launches automatically when Claude Code starts
- **Real-time visualization** — See agents walk around office rooms with speech bubbles
- **Cost tracking** — Token usage and dollar costs updated live
- **Subagent tree** — Visualize parallel agent execution
- **Self-awareness** — Claude can query its own session metrics via MCP tools

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- PixelPulse installed: `pip install pixelpulse`

## Installation

### Option 1: Claude Code Plugin Directory

```bash
# Clone or copy the plugin to your plugins directory
claude plugins add /path/to/pixelpulse/plugins/claude-code
```

### Option 2: Manual Install

```bash
# Copy the plugin directory
cp -r plugins/claude-code ~/.claude/plugins/pixelpulse
```

## Configuration

The plugin uses `userConfig` for customization. Set via Claude Code:

| Setting | Default | Description |
|---------|---------|-------------|
| `port` | `8765` | Dashboard server port |
| `auto_open_browser` | `true` | Open dashboard in browser on session start |
| `auto_stop_server` | `false` | Stop server when session ends |

## MCP Tools

Once installed, Claude can use these tools:

| Tool | Description |
|------|-------------|
| `pixelpulse_session_stats` | Token counts, costs, tool call count |
| `pixelpulse_cost_breakdown` | Per-model cost breakdown |
| `pixelpulse_subagent_tree` | Tree of spawned subagents |
| `pixelpulse_tool_summary` | Tool usage frequency |
| `pixelpulse_recent_events` | Last N session events |
| `pixelpulse_dashboard_url` | Dashboard URL and server status |

## Usage

After installation, just use Claude Code normally. The plugin:

1. Auto-starts the PixelPulse server on `SessionStart`
2. Forwards all hook events to the dashboard
3. Makes MCP tools available for session introspection

Try asking Claude: "How much have I spent so far?" or "What tools have I used most?"

## Troubleshooting

**Dashboard doesn't open:**
- Check that `pixelpulse` is installed: `pip install pixelpulse`
- Check the port isn't in use: `curl http://localhost:8765/api/health`

**Hooks not firing:**
- Verify plugin is installed: check `.claude/plugins/` directory
- Check Claude Code logs for hook errors

**MCP tools not available:**
- Ensure `uv` is installed: `uv --version`
- Check `.mcp.json` is in the plugin root
