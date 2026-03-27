# CLAUDE.md — PixelPulse

Guidance for Claude Code sessions on this repository.

## Commands

```bash
# Install (always use venv — never install globally)
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev,langgraph,otel]"

# Run tests
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m pytest tests/integration/ -v
.venv/Scripts/python.exe -m pytest tests/functional/ -v

# Visual tests (separate runner, not pytest)
.venv/Scripts/python.exe tests/visual/run_visual_tests.py

# Server
.venv/Scripts/python.exe -m uvicorn pixelpulse.server:app --reload --port 8765

# Lint
.venv/Scripts/python.exe -m ruff check src/
```

## Project Layout

```
src/pixelpulse/
  core.py          # PixelPulse class — main SDK entry point
  bus.py           # EventBus singleton (get_event_bus())
  protocol.py      # Event types + DASHBOARD_TYPE_MAP + to_dashboard_event()
  server.py        # FastAPI app (create_app())
  static/          # HTML/JS/CSS dashboard frontend
    modules/
      renderer.js  # Canvas2D render loop — CRITICAL: see gotchas below
tests/
  integration/     # Full wiring tests: pp.emit() → bus → /api/events
  functional/      # Adapter stack tests: LangGraph → pp → bus → HTTP
  e2e/             # LangGraph/OpenAI pipelines (mocked pp boundary)
  visual/          # Playwright visual tests (run_visual_tests.py)
```

## Architecture — Key Wiring

```
pp.agent_started()
  → emit_sync()
  → loop.create_task(bus.emit(event))   ← needs running event loop
  → bus._history                         ← singleton shared with server
  → GET /api/events                      ← to_dashboard_event() applied here
```

The bus is a **singleton** (`bus._bus` global). `PixelPulse.__init__` and `create_app()` both call `get_event_bus()` and get the same instance.

## Gotchas (learned the hard way)

### API paths
- Health endpoint: `/api/health` — NOT `/health` (returns 404)
- Events: `GET /api/events` — returns last 50, already converted via `to_dashboard_event()`
- WebSocket: `/ws/events`

### PixelPulse init
- `pipeline=` takes `list[str]` — e.g. `pipeline=["research", "content"]`
- NOT `list[dict]` — `[{"stage": "research"}]` will fail

### Dashboard event type mapping (DASHBOARD_TYPE_MAP)
`/api/events` does NOT return raw protocol types. `to_dashboard_event()` remaps them:

| Protocol type (emitted) | Dashboard type (at /api/events) | Distinguish via |
|---|---|---|
| `agent.started` | `agent_status` | `payload.status == "active"` |
| `agent.completed` | `agent_status` | `payload.status == "idle"` |
| `agent.thinking` | `agent_status` | `payload.status == "active"` |
| `message.sent` | `message_flow` | — |
| `cost.update` | `cost_update` | — |
| `run.started` | `pipeline_progress` | `payload.stage == "started"` |
| `run.completed` | `pipeline_progress` | `payload.stage == "completed"` |

**Never** assert `"started" in event["type"]` — the type is `"agent_status"`.

### Claude Code hook path — event type format
`/hooks/claude-code` uses an internal `_BusEmitter` that emits types like `"agent_started"` (underscores, NOT protocol dots like `"agent.started"`). These bypass `DASHBOARD_TYPE_MAP`, so `/api/events` returns `"agent_started"` NOT `"agent_status"`. Payload key is `"agent"` (not `"agent_id"`).

### @observe decorator — agent name key
`pp.agent_started("name", ...)` stores agent name as `payload["agent_id"]`. After `to_dashboard_event()`, check `e["payload"]["agent_id"]`, NOT `e["payload"]["agent"]`.

### Focus mode blank bug (FIXED)
`drawFocusOverlay()` originally used `destination-out` to "punch out" focused room — this ERASES room pixels. Fixed with `evenodd` clip: draw dim ONLY outside the focused room, leaving content untouched.

### Canvas fit issue (FIXED)
`resize()` had `baseZoom = Math.max(1, ...)` — prevents zoom below 1, causing rooms to overflow when content is large. Fixed to `Math.max(0.25, ...)`.

### renderer.js — infinite recursion risk
If editing `renderer.js`: `TEAM_STYLES` is a cache dict for `getTeamStyle()`.
- WRONG: replace `TEAM_STYLES[teamId]` references with `getTeamStyle(teamId)` inside `getTeamStyle` itself → infinite recursion → black canvas
- RIGHT: `if (TEAM_STYLES[teamId]) return TEAM_STYLES[teamId];` as the cache check

## Integration Test Patterns

### Singleton bus isolation (required for all integration/functional tests)
```python
@pytest.fixture(autouse=True)
def fresh_bus():
    import pixelpulse.bus as bus_module
    bus_module._bus = None
    yield
    bus_module._bus = None
```

### Async task flush
`emit_sync()` uses `loop.create_task()` — task is scheduled but not run immediately.
Always yield to the event loop before asserting on `/api/events`:
```python
pp.agent_started("researcher", task="Test")
await asyncio.sleep(0)   # let scheduled task execute
resp = await client.get("/api/events")
```

### ASGI transport
```python
from httpx import ASGITransport, AsyncClient

async with AsyncClient(
    transport=ASGITransport(app=pp._create_app()),
    base_url="http://test",
) as client:
    ...
```

## Test Structure

| Layer | Location | Count | What it tests |
|-------|----------|-------|---------------|
| Unit | `tests/test_*.py` | ~233 | Adapters, protocol, bus, decorators |
| E2E (graph) | `tests/e2e/` | ~20 | Real LangGraph + mocked pp boundary |
| Integration | `tests/integration/` | 8 | pp → bus → /api/events wiring |
| Functional | `tests/functional/` | 25 | LangGraph + @observe + OTEL + Claude Code hooks → bus → HTTP |
| Visual | `tests/visual/` | manual | Playwright screenshots |

## venv on Windows
Always use `.venv/Scripts/python.exe`, not `python` — the system Python won't have project deps.
Playwright: `.venv/Scripts/python.exe -m playwright install chromium`
