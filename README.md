<div align="center">

<br/>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://img.shields.io/badge/%E2%96%88%E2%96%88%20PixelPulse%20%E2%96%88%E2%96%88-Production%20Observability%20Meets%20Pixel%20Art-ff6ec7?style=for-the-badge&labelColor=0f172a" />
  <source media="(prefers-color-scheme: light)" srcset="https://img.shields.io/badge/%E2%96%88%E2%96%88%20PixelPulse%20%E2%96%88%E2%96%88-Production%20Observability%20Meets%20Pixel%20Art-ff6ec7?style=for-the-badge&labelColor=1e293b" />
  <img alt="PixelPulse" src="https://img.shields.io/badge/%E2%96%88%E2%96%88%20PixelPulse%20%E2%96%88%E2%96%88-Production%20Observability%20Meets%20Pixel%20Art-ff6ec7?style=for-the-badge&labelColor=0f172a" />
</picture>

<br/><br/>

**The observability dashboard your agents actually make you *want* to watch.**

<br/>

<a href="https://pypi.org/project/pixelpulse-dashboard/"><img src="https://img.shields.io/pypi/v/pixelpulse-dashboard.svg?style=flat-square&logo=python&logoColor=white&label=PyPI&color=3b82f6" alt="PyPI" /></a>&nbsp;
<a href="https://pypi.org/project/pixelpulse-dashboard/"><img src="https://img.shields.io/pypi/pyversions/pixelpulse-dashboard.svg?style=flat-square&label=Python&color=3b82f6" alt="Python" /></a>&nbsp;
<a href="https://marketplace.visualstudio.com/items?itemName=revankumard.pixelpulse"><img src="https://img.shields.io/visual-studio-marketplace/v/revankumard.pixelpulse?style=flat-square&logo=visual-studio-code&logoColor=white&label=VS%20Code&color=8b5cf6" alt="VS Code" /></a>&nbsp;
<a href="https://github.com/RevanKumarD/pixelpulse/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/RevanKumarD/pixelpulse/ci.yml?style=flat-square&logo=github&label=CI&color=22c55e" alt="CI" /></a>&nbsp;
<img src="https://img.shields.io/badge/tests-505%20passing-22c55e?style=flat-square" alt="Tests" />&nbsp;
<a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-64748b?style=flat-square" alt="License" /></a>

<br/><br/>

<img src="tests/visual/demo-preview.gif" alt="PixelPulse — agents thinking, messages flowing, costs tracking" width="820" style="image-rendering: pixelated; border-radius: 8px;" />

<br/>

> *Agents walk around pixel-art rooms, show speech bubbles when thinking,*
> *pass glowing particles between teams, and track cost per token — live.*

<br/>

<kbd>&nbsp; Install &nbsp;</kbd>&ensp;
<kbd>&nbsp; Quick Start &nbsp;</kbd>&ensp;
<kbd>&nbsp; 8 Adapters &nbsp;</kbd>&ensp;
<kbd>&nbsp; Screenshots &nbsp;</kbd>&ensp;
<kbd>&nbsp; API &nbsp;</kbd>&ensp;
<kbd>&nbsp; Roadmap &nbsp;</kbd>

<br/>

[Demo Videos](https://github.com/RevanKumarD/pixelpulse/releases/tag/demo-v1) ·
[VS Code Extension](https://marketplace.visualstudio.com/items?itemName=revankumard.pixelpulse) ·
[PyPI](https://pypi.org/project/pixelpulse-dashboard/) ·
[Issues](https://github.com/RevanKumarD/pixelpulse/issues) ·
[Contributing](CONTRIBUTING.md)

</div>

<br/>

---

<br/>

## &#x1F52D; The Problem

You're running a multi-agent pipeline. Something stalls. Which agent? What was it thinking?

<table>
<tr>
<th width="50%">&#x1F534;&ensp;What exists today</th>
<th width="50%">&#x1F7E2;&ensp;What's missing</th>
</tr>
<tr>
<td>

<kbd>Langfuse / AgentOps / Arize</kbd><br/>
Post-run traces — you find out *after* it fails

<kbd>Terminal output</kbd><br/>
Wall of text — no spatial awareness of who's where

<kbd>Custom JSON logging</kbd><br/>
Grep soup — no visual indication of data flow

<kbd>Grafana dashboards</kbd><br/>
Metrics without semantics — latency, not *reasoning*

</td>
<td>

**PixelPulse fills the gap:**

&#x2714; See *who* is active — spatially, in real time<br/>
&#x2714; Read *what* they're thinking — speech bubbles<br/>
&#x2714; Watch *where* data flows — glowing particles<br/>
&#x2714; Track *how much* it costs — live token counters<br/>
&#x2714; Know *which stage* you're in — pipeline tracker<br/>
&#x2714; Works with **any** Python agent framework

</td>
</tr>
</table>

<br/>

---

<br/>

## &#x26A1; Install

```bash
pip install pixelpulse-dashboard
```

That's it. No API keys. No config files. No Docker required.

<details>
<summary>&ensp;&#x1F4E6;&ensp;<strong>Framework extras</strong></summary>

<br/>

```bash
pip install "pixelpulse-dashboard[langgraph]"    # LangGraph
pip install "pixelpulse-dashboard[crewai]"       # CrewAI
pip install "pixelpulse-dashboard[openai]"       # OpenAI Agents SDK
pip install "pixelpulse-dashboard[autogen]"      # AutoGen
pip install "pixelpulse-dashboard[otel]"         # OpenTelemetry
pip install "pixelpulse-dashboard[all]"          # Everything
```

</details>

<br/>

> Works on **macOS**, **Linux**, and **Windows** &mdash; Python 3.10+

<br/>

---

<br/>

## &#x1F680; 30-Second Start

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
pp.serve()  # --> http://localhost:8765
```

```python
# From your agent code — anywhere, any framework
pp.agent_started("researcher", task="Searching for trends")
pp.agent_thinking("researcher", thought="Found 3 promising niches...")
pp.agent_message("researcher", "writer", content="Top pick: eco-denim", tag="data")
pp.agent_completed("researcher", output="Research complete")
```

Open `localhost:8765`. Your agents are walking around their office.

<br/>

---

<br/>

## &#x1F3A8; See It in Action

<div align="center">
<img src="tests/visual/screenshots/03_demo_active_13s.png" alt="Active dashboard" width="820" style="border-radius: 6px;" />
<br/><br/>
<sub><strong>4 teams active</strong> · pipeline progressing · event log streaming · cost tracking live</sub>
</div>

<br/>

<table>
<tr>
<td width="50%">

&#x1F3AD; **Pixel-art agents**<br/>
<sub>Characters walk, sit at desks, roam furnished rooms with warm lighting and team-colored accents. Not a static grid — they <em>move</em>.</sub>

&#x1F4AC; **Speech bubbles**<br/>
<sub>See exactly what each agent is thinking, not buried in logs. Word-wrapped, positioned, real-time.</sub>

&#x2728; **Message particles**<br/>
<sub>Glowing dots fly between rooms when agents communicate. You see data flow <em>spatially</em>.</sub>

&#x1F4CA; **Pipeline tracker**<br/>
<sub>Orchestrator bar shows which stage is active with progress indicators.</sub>

</td>
<td width="50%">

&#x1F4B0; **Live cost counter**<br/>
<sub>Per-agent and total cost with token breakdown. Updated on every LLM call.</sub>

&#x1F4DC; **Rich event log**<br/>
<sub>Timestamped, searchable, filterable. Color-coded type badges. Exportable as JSON.</sub>

&#x1F50D; **Focus mode**<br/>
<sub>Double-click any room to zoom in. Minimap shows position. ESC to return.</sub>

&#x1F464; **Agent detail panel**<br/>
<sub>Click any agent for 4-tab deep dive: overview, messages, reasoning, performance.</sub>

</td>
</tr>
</table>

<details>
<summary>&ensp;&#x1F5BC;&ensp;<strong>Screenshot gallery</strong></summary>

<br/>

<table>
<tr>
<td align="center"><img src="tests/visual/screenshots/20_api_message_particle.png" width="380" /><br/><sub>Message particles between rooms</sub></td>
<td align="center"><img src="tests/visual/screenshots/05_agent_detail_overview.png" width="380" /><br/><sub>Agent detail panel (4 tabs)</sub></td>
</tr>
<tr>
<td align="center"><img src="tests/visual/screenshots/15_zoomed_in.png" width="380" /><br/><sub>Focus mode with minimap</sub></td>
<td align="center"><img src="tests/visual/screenshots/13_light_theme.png" width="380" /><br/><sub>Light theme</sub></td>
</tr>
<tr>
<td align="center"><img src="tests/visual/screenshots/16_fit_view.png" width="380" /><br/><sub>Flow connectors (press F)</sub></td>
<td align="center"><img src="tests/visual/screenshots/12_settings_panel.png" width="380" /><br/><sub>Settings panel</sub></td>
</tr>
<tr>
<td align="center"><img src="tests/visual/screenshots/18_run_history_section.png" width="380" /><br/><sub>Persistent run history</sub></td>
<td align="center"><img src="tests/visual/screenshots/14_keyboard_help.png" width="380" /><br/><sub>Keyboard shortcuts overlay</sub></td>
</tr>
</table>

</details>

<br/>

---

<br/>

## &#x1F50C; Plug Into Any Framework

PixelPulse isn't tied to one agent framework. **2 lines of code. 8 frameworks.**

<br/>

<table>
<tr>
<th>Framework</th>
<th>Integration</th>
<th align="center">Lines to add</th>
</tr>
<tr>
<td><strong>LangGraph</strong></td>
<td><code>pp.adapter("langgraph").instrument(graph)</code></td>
<td align="center"><kbd>&nbsp;2&nbsp;</kbd></td>
</tr>
<tr>
<td><strong>CrewAI</strong></td>
<td><code>pp.adapter("crewai").instrument(crew)</code></td>
<td align="center"><kbd>&nbsp;2&nbsp;</kbd></td>
</tr>
<tr>
<td><strong>AutoGen</strong></td>
<td><code>pp.adapter("autogen").instrument(team)</code></td>
<td align="center"><kbd>&nbsp;2&nbsp;</kbd></td>
</tr>
<tr>
<td><strong>OpenAI Agents SDK</strong></td>
<td><code>pp.adapter("openai").instrument()</code></td>
<td align="center"><kbd>&nbsp;2&nbsp;</kbd></td>
</tr>
<tr>
<td><strong>Claude Code</strong></td>
<td><code>claude plugin add plugins/claude-code</code></td>
<td align="center"><kbd>&nbsp;0&nbsp;</kbd></td>
</tr>
<tr>
<td><strong>OpenTelemetry</strong></td>
<td>Set <code>OTEL_EXPORTER_OTLP_ENDPOINT</code> env var</td>
<td align="center"><kbd>&nbsp;0&nbsp;</kbd></td>
</tr>
<tr>
<td><strong>@observe</strong></td>
<td><code>@observe(pp, as_type="agent")</code></td>
<td align="center"><kbd>&nbsp;1&nbsp;</kbd></td>
</tr>
<tr>
<td><strong>Any Python</strong></td>
<td>Direct <code>pp.agent_*()</code> calls</td>
<td align="center"><kbd>&nbsp;~&nbsp;</kbd></td>
</tr>
</table>

<details>
<summary>&ensp;&#x1F4BB;&ensp;<strong>Full adapter examples</strong></summary>

<br/>

**LangGraph**
```python
adapter = pp.adapter("langgraph")
adapter.instrument(compiled_graph)
result = graph.invoke({"topic": "AI trends"})  # all nodes visualized automatically
```

**CrewAI**
```python
adapter = pp.adapter("crewai")
adapter.instrument(crew)
crew.kickoff()  # step_callback and task_callback patched
```

**OpenAI Agents SDK**
```python
adapter = pp.adapter("openai")
adapter.instrument()  # registers TracingProcessor globally — zero other changes
result = Runner.run_sync(agent, "What are the latest AI agent frameworks?")
```

**@observe Decorator**
```python
from pixelpulse.decorators import observe

@observe(pp, as_type="agent", name="researcher")
def research(query: str) -> str:
    return call_llm(query)  # start/thinking/complete events emitted automatically
```

**Claude Code Plugin**
```bash
claude plugin add /path/to/pixelpulse/plugins/claude-code
```
Auto-registers all 7 lifecycle hooks, auto-starts the server, adds 6 MCP tools for querying session stats, cost breakdowns, and subagent trees. See [plugins/claude-code/README.md](plugins/claude-code/README.md).

**OpenTelemetry**
```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8765 python my_agents.py
```

</details>

<br/>

---

<br/>

## &#x1F4E1; The Full API

<table>
<tr>
<td width="50%">

**Python Events**

```python
# Lifecycle
pp.run_started(run_id, name="Pipeline run")
pp.run_completed(run_id, total_cost=0.042)
pp.stage_entered("research")

# Agent state
pp.agent_started(id, task="...")
pp.agent_thinking(id, thought="...")
pp.agent_completed(id, output="...")
pp.agent_error(id, error="...")

# Communication
pp.agent_message(from_, to, content="...")
pp.cost_update(id, cost=0.005,
    tokens_in=1000, tokens_out=300)
pp.artifact_created(id, artifact_type="code",
    content="...")
```

</td>
<td width="50%">

**HTTP / WebSocket**

```
GET  /api/health        Health check
GET  /api/events        Last 50 events
GET  /api/config        Teams, agents, pipeline
WS   /ws/events         Real-time stream
POST /v1/traces         OTEL span ingestion
POST /hooks/claude-code Hook endpoint
```

<br/>

**Configuration**

```python
pp = PixelPulse(
    agents={"id": {"team": "t", "role": "R"}},
    teams={"t": {"label": "Name", "color": "#hex"}},
    pipeline=["stage-a", "stage-b"],
    title="My Dashboard",
)
pp.serve(port=8765, open_browser=True)
```

</td>
</tr>
</table>

<br/>

---

<br/>

## &#x2699; Under the Hood

<table>
<tr><th>Layer</th><th>Tech</th><th>Purpose</th></tr>
<tr><td><strong>Server</strong></td><td>FastAPI + WebSockets</td><td>Event ingestion, REST API, real-time push</td></tr>
<tr><td><strong>Storage</strong></td><td>SQLite via aiosqlite</td><td>Persistent run history, event replay</td></tr>
<tr><td><strong>Renderer</strong></td><td>Canvas 2D</td><td>60fps pixel-art: sprites, pathfinding, particles</td></tr>
<tr><td><strong>Adapters</strong></td><td>Protocol-based</td><td>Thin per-framework translation layer (~100 LOC each)</td></tr>
<tr><td><strong>Plugins</strong></td><td>MCP + hooks</td><td>Claude Code, VS Code, Codex, Gemini CLI</td></tr>
</table>

<br/>

---

<br/>

## &#x2328; Keyboard Shortcuts

<div align="center">

<kbd>F</kbd> Flow connectors &ensp;
<kbd>M</kbd> Minimap &ensp;
<kbd>T</kbd> Team filter &ensp;
<kbd>H</kbd> Help overlay &ensp;
<kbd>+</kbd> <kbd>-</kbd> Zoom &ensp;
<kbd>0</kbd> / <kbd>ESC</kbd> Fit view &ensp;
<kbd>Double-click</kbd> Focus mode

</div>

<br/>

---

<br/>

## &#x1F9EA; Test Coverage

<sub>505 tests across 6 layers — not just unit tests:</sub>

| Layer | Count | What it proves |
|:------|------:|:---------------|
| **Unit** | 270+ | Adapter logic, decorators, protocol, event bus, storage |
| **E2E** | 35 | Real LangGraph/OpenAI pipelines (mocked at pp boundary) |
| **Integration** | 25+ | `pp.agent_started()` &rarr; EventBus &rarr; `/api/events` wiring |
| **Functional** | 52 | All 7 adapters &rarr; real pp &rarr; bus &rarr; HTTP, zero mocks |
| **Plugin** | 22 | Hook handler, ensure_server, MCP aggregation |
| **Visual** | 17 | Playwright screenshots: idle, active, themes, errors |

<br/>

---

<br/>

## &#x1F5FA; Roadmap

**v0.3 &mdash; Usability** *(current)*

&ensp; &#x2705; Agent detail panel &middot; Claude Code plugin &middot; SQLite run history &middot; Replay engine
<br/>
&ensp; &#x2705; Video export &middot; OTEL ingestion &middot; VS Code extension &middot; PyPI package

**v0.4 &mdash; Distribution** *(next)*

&ensp; &#x2B1C; Codex / Gemini CLI plugins &middot; Cost alerting &middot; Custom sprite packs

**v0.5 &mdash; Integrations**

&ensp; &#x2B1C; Langchain &middot; Semantic Kernel &middot; n8n workflow

**v1.0 &mdash; Scale**

&ensp; &#x2B1C; Multi-session dashboard &middot; Cloud option &middot; 3D visualization

<br/>

---

<br/>

## &#x1F91D; Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, test instructions, and how to write a new adapter.

<br/>

---

<div align="center">

<br/>

**Apache-2.0** &mdash; Built by [Revan Kumar D](https://github.com/RevanKumarD)

<br/>

<sub>If PixelPulse helps you debug your agents faster, consider giving it a &#x2B50;</sub>

<br/><br/>

</div>
