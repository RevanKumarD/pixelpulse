# PixelPulse — Gemini CLI Integration

Watch your Gemini CLI agent sessions on the PixelPulse pixel-art dashboard.

## Setup

### 1. Start the PixelPulse server

```bash
pip install pixelpulse
pixelpulse --port 8765
```

### 2. Add MCP server to Gemini CLI

Add to your `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "pixelpulse": {
      "command": "uv",
      "args": ["run", "--script", "/path/to/pixelpulse/plugins/claude-code/mcp-server/server.py"],
      "env": {
        "PIXELPULSE_PORT": "8765"
      }
    }
  }
}
```

### 3. Open the dashboard

Navigate to `http://localhost:8765` to see your Gemini sessions in real time.

## Available MCP Tools

| Tool | Description |
|------|-------------|
| `pixelpulse_session_stats` | Current session cost, tokens, and tool metrics |
| `pixelpulse_cost_breakdown` | Per-model cost breakdown |
| `pixelpulse_subagent_tree` | Tree of spawned subagents |
| `pixelpulse_tool_summary` | Tool usage frequency |
| `pixelpulse_recent_events` | Last N session events |
| `pixelpulse_dashboard_url` | Dashboard URL and connection status |

## How It Works

Gemini CLI supports MCP servers natively. The PixelPulse MCP server provides read-only session analytics tools that connect to the PixelPulse dashboard API. The same MCP server works across Claude Code, Codex, Gemini CLI, Cursor, and any other MCP-compatible tool.
