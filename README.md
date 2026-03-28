# PixelPulse

**Watch your AI agents work — pixel-art observability for multi-agent systems.**

[![PyPI version](https://img.shields.io/pypi/v/pixelpulse.svg)](https://pypi.org/project/pixelpulse/)
[![Python](https://img.shields.io/pypi/pyversions/pixelpulse.svg)](https://pypi.org/project/pixelpulse/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![CI](https://github.com/RevanKumarD/pixelpulse/actions/workflows/ci.yml/badge.svg)](https://github.com/RevanKumarD/pixelpulse/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-505%20passing-brightgreen.svg)](tests/)

![PixelPulse Demo — agents roaming, messages flowing, pipeline progressing](tests/visual/demo-preview.gif)

> *Your agents walk around pixel-art office rooms, show speech bubbles when thinking, and pass glowing message particles between teams. One `pip install` and you're watching.*

**[Watch full demo videos](https://github.com/RevanKumarD/pixelpulse/releases/tag/demo-v1)** — 3 scenarios: Software Dev Team, Creative Agency, Data Science Lab

---

## Why PixelPulse?

You're running a multi-agent pipeline. Something stalls. Which agent failed? What was it thinking? Where did the handoff break?

Your options today: grep through JSON logs, wait for post-run traces in Langfuse/AgentOps, or stare at terminal output. None of these tell you what's happening *right now*.

PixelPulse gives you a **live dashboard** — see who's active, read their reasoning in speech bubbles, watch messages fly between teams, and track costs per token — all in real time. It works with any Python agent framework, or none at all.

---

## Install

```bash
pip install pixelpulse
```

Works on **macOS, Linux, and Windows** (Python 3.10+).

---

## Quick Start

```python
from pixelpulse import PixelPulse

pp = PixelPulse(
    agents={
        "researcher": {"team": "research", "role": "Finds information"},
        "writer":     {"team": "content",  "role": "Writes articles"},
    },
    teams={
        "research": {"label": "Research Lab",    "color": "#00d4ff"},
        "content":  {"label": "Content Studio",  "color": "#ff6ec7"},
    },
    pipeline=["research", "content"],
)
pp.serve()  # → http://localhost:8765
```

Then emit events from your agent code:

```python
pp.agent_started("researcher", task="Searching for trends")
pp.agent_thinking("researcher", thought="Found 3 promising niches...")
pp.agent_message("researcher", "writer", content="Top pick: eco-denim", tag="data")
pp.cost_update("researcher", cost=0.003, tokens_in=1200, tokens_out=400)
pp.agent_completed("researcher", output="Research complete")
```

Open `http://localhost:8765` — your agents appear as pixel-art characters in their team rooms.

---

## What You See

![Agents at work — 4 teams, pipeline tracker, event log, cost counter](tests/visual/screenshots/03_demo_active_13s.png)

<table>
<tr>
<td width="50%">

**Pixel-art agents** — Animated characters that walk, work at desks, and roam their furnished office rooms with warm lighting and team-colored accents.

**Speech bubbles** — Agent reasoning and messages appear as word-wrapped bubbles above each character as they think and communicate.

**Message particles** — Glowing dots fly between agents across rooms when messages are sent, showing data flow in real time.

**Pipeline tracker** — Central orchestrator bar shows which stage is active, with progress indicators for each pipeline phase.

</td>
<td width="50%">

**Cost counter** — Live per-agent and total cost with token breakdown (input/output), updated as each LLM call completes.

**Event log** — Timestamped, searchable, filterable log of all agent events with color-coded type badges.

**Focus mode** — Double-click any room to zoom in and inspect individual agents. ESC to return.

**Dark + Light themes** — Full theme toggle with pixel-art aesthetic in both modes.

</td>
</tr>
</table>

### Message Flow

Agents communicate across rooms with glowing particles, speech bubbles, and a rich event log:

![Message flow — particles between rooms, speech bubbles, event log](tests/visual/screenshots/20_api_message_particle.png)

### Focus Mode

Double-click any room to zoom in. A minimap appears showing your position. Press ESC or 0 to return:

![Focus mode — zoomed into room with minimap](tests/visual/screenshots/15_zoomed_in.png)

### Flow Connectors

Press `F` to show dashed pipeline arrows between rooms, visualizing the data flow path:

![Flow connectors — dashed arrows between rooms](tests/visual/screenshots/16_fit_view.png)

### Light Theme

Toggle between dark and light themes:

![Light theme](tests/visual/screenshots/13_light_theme.png)

---

## Framework Adapters

PixelPulse integrates with all major agent frameworks. Pick the one that matches your stack:

| Framework | Adapter | How it works |
|-----------|---------|--------------|
| **LangGraph** | `pp.adapter("langgraph")` | Wraps `graph.invoke/ainvoke`, auto-maps nodes to agents |
| **CrewAI** | `pp.adapter("crewai")` | Patches `crew.kickoff()`, `step_callback`, `task_callback` |
| **AutoGen** (agentchat) | `pp.adapter("autogen")` | Wraps `team.run_stream()` async generator |
| **OpenAI Agents SDK** | `pp.adapter("openai")` | Registers a `TracingProcessor` (no code changes needed) |
| **@observe decorator** | `from pixelpulse.decorators import observe` | Decorator-based, framework-agnostic |
| **OpenTelemetry (OTEL)** | Built-in endpoint | POST GenAI spans to `/v1/traces` |
| **Claude Code hooks** | Built-in endpoint | POST hooks to `/hooks/claude-code` |
| **Generic / Manual** | Direct `pp.*()` calls | Works with any Python agent system |

### LangGraph

```python
adapter = pp.adapter("langgraph")
adapter.instrument(compiled_graph)
result = graph.invoke({"topic": "AI trends"})
```

### CrewAI

```python
adapter = pp.adapter("crewai")
adapter.instrument(crew)
crew.kickoff()
```

### AutoGen

```python
adapter = pp.adapter("autogen")
adapter.instrument(team)
async for msg in team.run_stream(task="Research AI trends"):
    pass
```

### OpenAI Agents SDK

```python
adapter = pp.adapter("openai")
adapter.instrument()  # registers globally — no other changes needed
result = Runner.run_sync(agent, "What are the latest AI agent frameworks?")
```

### @observe Decorator

```python
from pixelpulse.decorators import observe

@observe(pp, as_type="agent", name="researcher")
def research(query: str) -> str:
    return call_llm(query)  # start/complete events emitted automatically

@observe(pp, as_type="tool", name="web-search")
def search(q: str) -> str:
    return fetch_results(q)  # thinking + artifact events
```

### OpenTelemetry

Any framework that exports OTEL GenAI spans works automatically:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8765 python my_agents.py
```

### Claude Code Plugin (Recommended)

Install the PixelPulse plugin for automatic hook registration, MCP tools, and session analytics:

```bash
claude plugin add /path/to/pixelpulse/plugins/claude-code
```

This gives you:
- **Auto-registered hooks** — All 7 lifecycle events (SessionStart → SessionEnd) stream to the dashboard
- **Auto-start server** — Dashboard launches on first SessionStart
- **6 MCP tools** — `get_session_stats`, `get_cost_breakdown`, `get_subagent_tree`, `get_recent_tool_calls`, `get_active_agents`, `get_session_events`
- **Session analyzer agent** — `/session-analyzer` for efficiency insights

See [plugins/claude-code/README.md](plugins/claude-code/README.md) for configuration.

### Claude Code Hooks (Manual)

Or add hooks manually to `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse":  [{"matcher": "*", "hooks": [{"type": "command", "command": "curl -s -X POST http://localhost:8765/hooks/claude-code -H 'Content-Type: application/json' -d @-"}]}],
    "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "curl -s -X POST http://localhost:8765/hooks/claude-code -H 'Content-Type: application/json' -d @-"}]}]
  }
}
```

---

## Configuration

```python
pp = PixelPulse(
    agents={
        "agent-id": {
            "team": "team-id",        # which room to place agent in
            "role": "Role description", # shown in agent card
        }
    },
    teams={
        "team-id": {
            "label": "Display Name",   # room header label
            "color": "#00d4ff",        # room accent color (hex)
        }
    },
    pipeline=["stage-a", "stage-b"],   # ordered list of pipeline stages
    title="My Dashboard",              # browser tab title
)

pp.serve(port=8765, open_browser=True)  # start dashboard
```

### Event API

```python
# Run lifecycle
pp.run_started(run_id, name="Run name")
pp.run_completed(run_id, status="completed", total_cost=0.01)
pp.stage_entered(stage_name, run_id=run_id)
pp.stage_exited(stage_name, run_id=run_id)

# Agent events
pp.agent_started(agent_id, task="What the agent is doing")
pp.agent_thinking(agent_id, thought="Agent's internal reasoning")
pp.agent_completed(agent_id, output="What the agent produced")
pp.agent_error(agent_id, error="Error message")

# Communication
pp.agent_message(from_agent, to_agent, content="Message text", tag="data")
pp.cost_update(agent_id, cost=0.005, tokens_in=1000, tokens_out=300, model="gpt-4o-mini")
pp.artifact_created(agent_id, artifact_type="text", content="Output content")
```

### HTTP API

```
GET  /api/health          → {"status": "ok"}
GET  /api/events          → last 50 dashboard events
GET  /api/config          → teams, agents, pipeline config
WS   /ws/events           → real-time event stream
POST /v1/traces           → OTEL span ingestion
POST /hooks/claude-code   → Claude Code hook endpoint
```

---

## Setup by Platform

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pixelpulse

# With framework extras:
pip install "pixelpulse[langgraph]"   # LangGraph
pip install "pixelpulse[otel]"        # OpenTelemetry
```

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install pixelpulse
```

### Docker

```bash
docker run -p 8765:8765 pixelpulse/pixelpulse
```

Or with docker-compose:

```yaml
services:
  pixelpulse:
    image: pixelpulse/pixelpulse
    ports:
      - "8765:8765"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./my_agents.py:/app/my_agents.py
    command: python /app/my_agents.py
```

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `F` | Toggle flow connectors |
| `M` | Toggle minimap |
| `T` | Filter teams |
| `0` / `ESC` | Fit all rooms in view |
| `+` / `-` | Zoom in / out |
| `H` | Help overlay |
| Double-click room | Focus mode |

---

## Dashboard Features

| Feature | Details |
|---------|---------|
| **Room sizing** | Uniform, Adaptive (scales by agent count), or Compact layout modes |
| **Collapsible rooms** | Click team label to collapse to a compact badge |
| **Resizable panels** | Drag sidebar and bottom bar edges to resize |
| **Settings panel** | Gear icon opens full settings: scanlines, font scale, connectors, room sizing |
| **Screenshot export** | Camera button exports the canvas as PNG |
| **Event export** | Download all events as JSON for offline analysis |
| **Demo mode** | Built-in demo with speed control (1x-10x) to showcase features |

---

## Test Coverage

505 tests across 5 layers:

| Layer | Count | What it proves |
|-------|-------|----------------|
| Unit | 270+ | Adapter logic, decorators, protocol, event bus, storage models |
| E2E (graph-level) | 35 | Real LangGraph/OpenAI pipelines with mocked pp boundary |
| Integration | 25+ | `pp.agent_started()` → EventBus → `/api/events` wiring + plugin hook→event flow + storage lifecycle |
| Functional | 52 | All 7 adapter paths → real pp → bus → HTTP, no mocks |
| Plugin | 22 | Hook handler parsing, ensure_server, MCP aggregation functions |
| Visual | 17 | Playwright screenshots: idle, demo, detail panel, themes, API pipeline, errors |

---

## Roadmap

### v0.3 — Usability (current)
- [x] Agent click → detail panel with event history (4 tabs)
- [x] Readable fonts at all zoom levels
- [x] Enhanced office visuals (lighting, furniture, carpets)
- [x] Claude Code plugin with hooks, MCP server, and session analytics
- [x] Persistent run history with SQLite backend
- [x] Run replay engine with playback controls
- [x] Video export (WebM recording of dashboard)
- [x] Accurate per-MTok pricing for all major providers (March 2026)
- [x] OpenTelemetry GenAI semantic conventions ingestion

### v0.4 — Distribution (next)
- [ ] VS Code extension (watch your Claude Code session live)
- [ ] Codex CLI / Gemini CLI plugin packages
- [ ] PyPI stable release with versioned API
- [ ] Cost alerting thresholds

### v0.5 — Integrations
- [ ] Langchain adapter
- [ ] Semantic Kernel adapter
- [ ] n8n workflow integration

### v1.0 — Scale
- [ ] Multi-session dashboard (compare runs side-by-side)
- [ ] Hosted cloud option (optional, privacy-first)
- [ ] Custom sprite packs

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, test instructions, and how to write a new adapter.

## License

Apache-2.0 — [RevanKumarD/pixelpulse](https://github.com/RevanKumarD/pixelpulse)
