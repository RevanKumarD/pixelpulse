# PixelPulse

Real-time pixel-art dashboard for multi-agent systems. Production observability meets engaging visualization.

```
pip install pixelpulse
```

## Quick Start

```python
from pixelpulse import PixelPulse

pp = PixelPulse(
    agents={
        "researcher": {"team": "research", "role": "Finds information"},
        "writer": {"team": "content", "role": "Writes articles"},
    },
    teams={
        "research": {"label": "Research Lab", "color": "#00d4ff"},
        "content": {"label": "Content Studio", "color": "#ff6ec7"},
    },
)
pp.serve()  # Opens pixel-art dashboard at http://localhost:8765
```

Then emit events from your agent code:

```python
pp.agent_started("researcher", task="Searching for trends")
pp.agent_message("researcher", "writer", content="Found 5 trends", tag="data")
pp.agent_completed("researcher", output="Full research output here")
pp.cost_update("researcher", cost=0.003, tokens_in=1200, tokens_out=400)
```

## Framework Adapters

### CrewAI

```python
from pixelpulse import PixelPulse

pp = PixelPulse(agents={...})
adapter = pp.adapter("crewai")
adapter.instrument(my_crew)
pp.serve()
```

### Generic (any Python agent system)

```python
pp = PixelPulse(agents={...})

# In your agent code, emit events directly:
pp.agent_started("my-agent", task="Working on it")
pp.agent_thinking("my-agent", thought="Considering options A, B, C...")
pp.agent_message("agent-a", "agent-b", content="Here's the data")
pp.agent_completed("my-agent", output="Done!")
```

## What You Get

- Animated pixel-art characters representing your agents
- Real-time agent-to-agent communication particles
- Speech bubbles showing agent reasoning
- Pipeline stage progression
- Cost and token tracking per agent
- Rich event log
- Dark and light themes
- Keyboard shortcuts

## Why PixelPulse?

Production observability tools (AgentOps, Langfuse, Arize Phoenix) have great tracing but boring dashboards.

Pixel-art visualization tools (Pixel Agents) are fun but have zero production utility.

PixelPulse combines both: **engaging visualization + real observability**.

## License

Apache-2.0
