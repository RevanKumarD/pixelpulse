# PixelPulse — Codex CLI Integration

Watch your Codex CLI agent sessions on the PixelPulse pixel-art dashboard.

## Setup

### 1. Start the PixelPulse server

```bash
pip install pixelpulse
pixelpulse --port 8765
```

Or from Python:

```python
from pixelpulse import PixelPulse

pp = PixelPulse(
    agents={"codex": {"team": "engineering", "role": "AI coding agent"}},
    teams={"engineering": {"label": "Engineering", "color": "#39ff14"}},
)
pp.serve(port=8765)
```

### 2. Add MCP server to Codex

Add to your `~/.codex/config.json`:

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

Or if installed via pip:

```json
{
  "mcpServers": {
    "pixelpulse": {
      "command": "python",
      "args": ["-m", "pixelpulse.mcp"],
      "env": {
        "PIXELPULSE_PORT": "8765"
      }
    }
  }
}
```

### 3. Open the dashboard

Navigate to `http://localhost:8765` to see your Codex sessions in real time.

## Available MCP Tools

Once configured, Codex can use these tools:

| Tool | Description |
|------|-------------|
| `pixelpulse_session_stats` | Current session cost, tokens, and tool metrics |
| `pixelpulse_cost_breakdown` | Per-model cost breakdown |
| `pixelpulse_subagent_tree` | Tree of spawned subagents |
| `pixelpulse_tool_summary` | Tool usage frequency |
| `pixelpulse_recent_events` | Last N session events |
| `pixelpulse_dashboard_url` | Dashboard URL and connection status |

## Event Ingestion

Codex can also POST events directly to the PixelPulse API:

```bash
curl -X POST http://localhost:8765/api/events/ingest \
  -H "Content-Type: application/json" \
  -d '{"type": "agent.started", "payload": {"agent_id": "codex", "task": "Implementing feature X"}}'
```

## How It Works

The PixelPulse MCP server connects to the PixelPulse dashboard's HTTP API to fetch and aggregate session data. It reuses the same MCP server as the Claude Code plugin — the protocol is framework-agnostic.

Codex's native MCP support means no additional adapters are needed. The MCP server exposes read-only tools for session introspection, while the dashboard receives live events via WebSocket or HTTP POST.
