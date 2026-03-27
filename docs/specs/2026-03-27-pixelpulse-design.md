# PixelPulse Design Spec

**Date**: 2026-03-27
**Status**: Approved (autonomous overnight build)
**Author**: Claude + Revan

## Problem Statement

The agent observability market in 2026 splits into two non-overlapping categories:

1. **Production observability** (AgentOps, Langfuse, Arize Phoenix, LangSmith) — full cost tracking, trace trees, agent graphs, evals. But boring standard dashboards with no engagement.
2. **Pixel-art visualization** (Pixel Agents, AgentRoom) — fun, engaging, intuitive. But zero production utility — no costs, no logs, no artifacts, no pipeline stages.

**Nobody combines both.** PixelPulse fills this gap.

## What PixelPulse Is

A Python package that gives any multi-agent system a real-time pixel-art dashboard with production-grade observability.

```python
from pixelpulse import PixelPulse

pp = PixelPulse(
    agents={
        "researcher": {"team": "research", "role": "Finds information"},
        "writer": {"team": "content", "role": "Writes articles"},
    },
    teams={
        "research": {"label": "Research", "color": "#00d4ff"},
        "content": {"label": "Content", "color": "#ff6ec7"},
    },
)
pp.serve(port=8765)  # Opens browser with pixel-art dashboard

# Emit events from your agent code
pp.agent_started("researcher", task="Searching for trends")
pp.agent_message("researcher", "writer", content="Found 5 trends", tag="data")
pp.agent_completed("researcher", output="Full research output here...")
pp.artifact_created("writer", artifact_type="text", content="Draft article...")
pp.cost_update("researcher", cost=0.003, tokens_in=1200, tokens_out=400)
```

## What PixelPulse Is NOT

- Not an LLM proxy (that's Helicone/Portkey)
- Not a trace storage backend (that's Langfuse/Phoenix)
- Not an eval framework (that's Braintrust/Phoenix)
- Not an IDE extension (that's Pixel Agents)

PixelPulse is **the visualization layer** — it consumes events and renders them beautifully.

## Architecture

```
User's Agent System
     │
     ├── pixelpulse SDK (Python)
     │   ├── emit events via pp.agent_started(), pp.agent_message(), etc.
     │   ├── OR use framework adapters (CrewAI, LangGraph, AutoGen, OpenAI)
     │   └── OR emit raw events via pp.emit({...})
     │
     ▼
PixelPulse Server (FastAPI, embedded)
     │
     ├── Event Bus (in-process async)
     ├── WebSocket /ws/events → Browser
     ├── REST API /api/events, /api/agents, /api/runs
     └── Static file server (dashboard assets)
     │
     ▼
PixelPulse Dashboard (Browser)
     ├── Canvas 2D pixel-art office (agents as animated characters)
     ├── Event log (rich formatted)
     ├── Cost tracker (per-agent, total)
     ├── Pipeline stage indicator
     ├── Agent communication particles
     ├── Speech bubbles with agent reasoning
     └── Artifact gallery (images, text, files)
```

## Event Protocol

PixelPulse uses a minimal event protocol inspired by OpenTelemetry GenAI semantic conventions.

### Event Types

| Type | Description | Key Fields |
|------|-------------|------------|
| `agent.started` | Agent begins work | agent_id, task, team |
| `agent.completed` | Agent finishes | agent_id, output, duration_ms |
| `agent.error` | Agent encountered error | agent_id, error, traceback |
| `agent.thinking` | Agent reasoning step | agent_id, thought |
| `message.sent` | Agent-to-agent message | from, to, content, tag |
| `pipeline.stage_entered` | Pipeline stage transition | stage, run_id |
| `pipeline.stage_exited` | Stage completed | stage, run_id, duration_ms |
| `artifact.created` | Output artifact produced | agent_id, type, uri/content |
| `cost.update` | Token/cost accounting | agent_id, cost, tokens_in, tokens_out, model |
| `run.started` | Pipeline run begins | run_id, name |
| `run.completed` | Pipeline run finishes | run_id, status, total_cost |

### Event Envelope

```json
{
  "id": "evt_01abc...",
  "type": "agent.started",
  "timestamp": "2026-03-27T01:30:00Z",
  "source": {
    "framework": "crewai",
    "service": "my-agent-app"
  },
  "correlation": {
    "run_id": "run_01xyz...",
    "trace_id": "optional-otel-trace-id",
    "span_id": "optional-otel-span-id"
  },
  "payload": {
    "agent_id": "researcher",
    "task": "Searching for market trends",
    "team": "research"
  }
}
```

## SDK Design

### Core API (`pixelpulse.PixelPulse`)

```python
class PixelPulse:
    def __init__(
        self,
        agents: dict[str, AgentConfig],     # Required: agent definitions
        teams: dict[str, TeamConfig] = None, # Optional: team groupings
        pipeline: list[str] = None,          # Optional: pipeline stage names
        title: str = "PixelPulse",           # Dashboard title
        theme: str = "dark",                 # dark | light
        port: int = 8765,                    # Server port
    ): ...

    # --- Lifecycle ---
    def serve(self, open_browser: bool = True) -> None: ...  # Start server (blocking)
    async def serve_async(self) -> None: ...                  # Start server (async)

    # --- Convenience emitters ---
    def agent_started(self, agent_id: str, task: str = "", **kw) -> None: ...
    def agent_completed(self, agent_id: str, output: str = "", **kw) -> None: ...
    def agent_error(self, agent_id: str, error: str = "", **kw) -> None: ...
    def agent_thinking(self, agent_id: str, thought: str = "", **kw) -> None: ...
    def agent_message(self, from_id: str, to_id: str, content: str = "", tag: str = "data", **kw) -> None: ...
    def stage_entered(self, stage: str, run_id: str = "", **kw) -> None: ...
    def stage_exited(self, stage: str, run_id: str = "", **kw) -> None: ...
    def artifact_created(self, agent_id: str, artifact_type: str = "text", **kw) -> None: ...
    def cost_update(self, agent_id: str, cost: float = 0, tokens_in: int = 0, tokens_out: int = 0, **kw) -> None: ...
    def run_started(self, run_id: str, name: str = "", **kw) -> None: ...
    def run_completed(self, run_id: str, status: str = "completed", **kw) -> None: ...

    # --- Raw emission ---
    def emit(self, event: dict) -> None: ...

    # --- Framework adapters ---
    def adapter(self, framework: str) -> BaseAdapter: ...
```

### AgentConfig and TeamConfig

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class AgentConfig:
    role: str = ""              # Human-readable role description
    team: str = "default"       # Team ID
    sprite: str = "default"     # Character sprite variant

@dataclass(frozen=True)
class TeamConfig:
    label: str = ""             # Display name
    color: str = "#64748b"      # Team color (hex)
    icon: str = ""              # Optional emoji icon
    role: str = ""              # Team role description
```

## Framework Adapters

Each adapter wraps a framework's native event/callback system and translates to PixelPulse events.

### Adapter Interface

```python
class BaseAdapter(Protocol):
    def instrument(self, target: Any) -> None: ...  # Attach to framework object
    def detach(self) -> None: ...                    # Remove instrumentation
```

### Supported Frameworks (MVP)

1. **CrewAI** — via event listeners (`@listen`)
2. **LangGraph** — via callbacks
3. **OpenAI Agents SDK** — via tracing hooks
4. **AutoGen** — via OpenTelemetry (already OTel-native)
5. **Generic** — manual `pp.emit()` calls

### Example: CrewAI

```python
from pixelpulse import PixelPulse
from pixelpulse.adapters.crewai import CrewAIAdapter

pp = PixelPulse(agents={...}, teams={...})
adapter = CrewAIAdapter(pp)
adapter.instrument(my_crew)  # Hooks into CrewAI event system

pp.serve()
```

## Dashboard Components (Ported from PixelPulse)

### Reused from PixelPulse

| Component | Source File | What Changes |
|-----------|------------|--------------|
| Canvas renderer | `renderer.js` | Remove hardcoded team/agent names, use config |
| Sprite system | `sprites.js` | Keep as-is (generic character sprites) |
| State store | `state.js` | Replace hardcoded TEAMS/AGENTS with dynamic config |
| WebSocket client | `ws-client.js` | Adapt event type names |
| Theme system | `theme.js` | Keep as-is |
| Settings | `settings.js`, `settings-panel.js` | Keep as-is |
| Keyboard shortcuts | `keyboard.js` | Keep as-is |
| Toasts | `toasts.js` | Keep as-is |
| Agent detail panel | `agent-detail.js` | Generalize |

### New Components for PixelPulse

| Component | Purpose |
|-----------|---------|
| Config loader | Fetch agent/team config from `/api/config` at startup |
| Artifact gallery | Display generated artifacts (images, text, files) |
| Run timeline | Visual timeline of pipeline stages |
| Cost dashboard | Per-agent and total cost breakdown |

### Key Generalization

The PixelPulse dashboard has hardcoded:
```js
export const TEAMS = { research: {...}, design: {...}, commerce: {...}, learning: {...} };
export const AGENT_ROLES = { "data-collector": "Scans trend sources", ... };
```

PixelPulse will load this dynamically:
```js
// On startup, fetch from server
const config = await fetch("/api/config").then(r => r.json());
// config.teams, config.agents, config.pipeline loaded at runtime
```

## File Structure

```
PixelPulse/
├── README.md
├── LICENSE                          (Apache-2.0)
├── pyproject.toml
├── docs/
│   ├── specs/
│   │   └── 2026-03-27-pixelpulse-design.md
│   └── guides/
│       ├── quickstart.md
│       └── adapters.md
├── src/
│   └── pixelpulse/
│       ├── __init__.py              # PixelPulse class + public API
│       ├── server.py                # FastAPI server (dashboard + WS + REST)
│       ├── protocol.py              # Event types, envelope, validation
│       ├── bus.py                    # Async event bus (from PixelPulse)
│       ├── config.py                # AgentConfig, TeamConfig dataclasses
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py              # BaseAdapter protocol
│       │   ├── crewai.py            # CrewAI event listener adapter
│       │   ├── langgraph.py         # LangGraph callback adapter
│       │   ├── openai_agents.py     # OpenAI Agents SDK adapter
│       │   ├── autogen.py           # AutoGen OTel adapter
│       │   └── generic.py           # Generic manual adapter
│       └── static/                  # Dashboard frontend (ported from PixelPulse)
│           ├── index.html
│           ├── dashboard.js
│           ├── modules/
│           │   ├── state.js          # Dynamic config, not hardcoded
│           │   ├── renderer.js       # Canvas 2D pixel-art office
│           │   ├── sprites.js        # Character sprite system
│           │   ├── ws-client.js      # WebSocket connection
│           │   ├── theme.js          # Dark/light themes
│           │   ├── settings.js       # Persistent settings
│           │   ├── settings-panel.js # Settings UI
│           │   ├── keyboard.js       # Keyboard shortcuts
│           │   ├── toasts.js         # Toast notifications
│           │   ├── agent-detail.js   # Agent click-to-inspect
│           │   └── demo.js           # Demo mode
│           └── assets/
│               └── characters.png    # Sprite sheet
├── tests/
│   ├── test_protocol.py
│   ├── test_bus.py
│   ├── test_server.py
│   └── test_adapters/
│       └── test_crewai.py
└── examples/
    ├── basic.py                     # Minimal example
    ├── crewai_example.py
    ├── langgraph_example.py
    └── custom_agents.py
```

## License

Apache-2.0 — matching OpenTelemetry/Prometheus ecosystem for maximum adoption.

## MVP Scope

### In Scope (Build Now)
- Core Python SDK with event emission
- FastAPI server serving dashboard + WebSocket
- Ported pixel-art dashboard with dynamic config
- Event protocol with all types
- Generic adapter (manual emission)
- CrewAI adapter (first framework)
- Basic cost tracking display
- Event log display
- Agent communication particles
- Speech bubbles
- Pipeline stage indicator
- Dark/light themes
- `pip install pixelpulse`

### Out of Scope (Future)
- OpenTelemetry OTLP ingestion
- Persistent storage (ClickHouse/Postgres)
- Artifact gallery with image previews
- LangGraph, AutoGen, OpenAI adapters (stubs only)
- Custom sprite themes
- Multi-run comparison
- Alerting/notifications
- Cloud hosted version

## Success Criteria

1. `pip install pixelpulse` works
2. 5-line setup gets a working dashboard
3. Dashboard shows animated pixel-art agents
4. Real-time events flow via WebSocket
5. Cost tracking visible per agent
6. Agent-to-agent communication visualized with particles
7. Works with CrewAI out of the box
8. Works with any Python agent system via manual emission
