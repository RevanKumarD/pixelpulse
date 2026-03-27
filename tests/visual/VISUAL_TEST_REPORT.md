# PixelPulse Visual Test Report

> Generated: 2026-03-27 14:49:03
> Tests: 9 scenarios, 35 screenshots
> Model: gpt-4o-mini (cheapest available)

## Test Results

| # | Test | Status |
|---|------|--------|
| 1 | Demo Mode + Dynamic Canvas | PASS |
| 2 | LangGraph Adapter (Real OpenAI) | PASS |
| 3 | @observe Decorator (Real OpenAI) | PASS |
| 4 | OTEL Ingestion | PASS |
| 5 | Manual Events (Generic) | PASS |
| 6 | Focus Mode — evenodd clip fix verified | PASS |
| 7 | Stress: 1 Room, 1 Agent | PASS |
| 8 | Stress: 10 Agents Overflow | PASS |
| 9 | Stress: 6 Rooms Fit View | PASS |

---

### 01 Dashboard Idle

**Dashboard Idle State**: Initial dashboard render with all teams visible, agents idle.

![Dashboard Idle State](screenshots/01_dashboard_idle.png)

### 02 Demo Agents Active

**Demo Mode — Agents Active**: Demo mode started. Agents show running animations, speech bubbles display thinking.

![Demo Mode — Agents Active](screenshots/02_demo_agents_active.png)

### 03 Demo Messages Flowing

**Demo Mode — Messages Flowing**: Inter-agent message particles visible between rooms.

![Demo Mode — Messages Flowing](screenshots/03_demo_messages_flowing.png)

### 04 Flow Connectors

**Flow Connectors**: Dashed pipeline flow lines between rooms (F key toggle).

![Flow Connectors](screenshots/04_flow_connectors.png)

### 05 Focus Mode Room1

**Focus Mode — Room 1**: Double-click zoom into Research Lab. Other rooms dimmed.

![Focus Mode — Room 1](screenshots/05_focus_mode_room1.png)

### 06 Focus Mode Room2

**Focus Mode — Room 2**: Focus on Design Studio via keyboard shortcut (2 key).

![Focus Mode — Room 2](screenshots/06_focus_mode_room2.png)

### 07 Keyboard Help

**Keyboard Help**: Help dialog showing all keyboard shortcuts (? key).

![Keyboard Help](screenshots/07_keyboard_help.png)

### 08 Demo Pipeline Progress

**Pipeline Progress**: Demo showing pipeline stage progression with cost accumulation.

![Pipeline Progress](screenshots/08_demo_pipeline_progress.png)

### 10 Langgraph Before

**LangGraph — Before**: Dashboard ready before LangGraph pipeline starts.

![LangGraph — Before](screenshots/10_langgraph_before.png)

### 11 Langgraph Running

**LangGraph — Running**: Real gpt-4o-mini call in progress via LangGraph adapter.

![LangGraph — Running](screenshots/11_langgraph_running.png)

### 12 Langgraph Midway

**LangGraph — Midway**: Multiple agents processed, messages flowing between nodes.

![LangGraph — Midway](screenshots/12_langgraph_midway.png)

### 13 Langgraph Complete

**LangGraph — Complete**: LangGraph pipeline completed. All events captured.

![LangGraph — Complete](screenshots/13_langgraph_complete.png)

### 14 Observe Running

**@observe — Running**: Decorated functions executing with real OpenAI calls.

![@observe — Running](screenshots/14_observe_running.png)

### 15 Observe Midway

**@observe — Midway**: Nested tool call (web-search) visible as agent thinking.

![@observe — Midway](screenshots/15_observe_midway.png)

### 16 Observe Complete

**@observe — Complete**: Full @observe pipeline completed with cost tracking.

![@observe — Complete](screenshots/16_observe_complete.png)

### 17 Otel Ingestion

**OTEL Ingestion**: Events received from synthetic OTEL spans via /v1/traces.

![OTEL Ingestion](screenshots/17_otel_ingestion.png)

### 18 Manual Researcher Active

**Manual — Researcher Active**: Manual event emission: researcher agent scanning signals.

![Manual — Researcher Active](screenshots/18_manual_researcher_active.png)

### 19 Manual Message Flow

**Manual — Message Flow**: Agent-to-agent message: researcher passing data to writer.

![Manual — Message Flow](screenshots/19_manual_message_flow.png)

### 20 Manual Writer Active

**Manual — Writer Active**: Writer agent processing brief with thinking bubbles.

![Manual — Writer Active](screenshots/20_manual_writer_active.png)

### 21 Manual Complete

**Manual — Complete**: Full manual event pipeline complete with cost summary.

![Manual — Complete](screenshots/21_manual_complete.png)

### 22 Focus Overview

**Focus — Overview Before**: Dashboard overview before entering focus mode.

![Focus — Overview Before](screenshots/22_focus_overview.png)

### 23 Focus Room1 Content

**Focus — Room 1 Content**: Focus mode: Room 1 content visible (not blank). evenodd clip fix verified.

![Focus — Room 1 Content](screenshots/23_focus_room1_content.png)

### 24 Focus Room2 Content

**Focus — Room 2 Content**: Focus mode: Room 2 content visible with dim overlay on other rooms.

![Focus — Room 2 Content](screenshots/24_focus_room2_content.png)

### 25 Focus Room3 Content

**Focus — Room 3 Content**: Focus mode: Room 3 focused, agents and furniture visible.

![Focus — Room 3 Content](screenshots/25_focus_room3_content.png)

### 26 Focus Return Overview

**Focus — Return Overview**: ESC returns to overview with all rooms visible.

![Focus — Return Overview](screenshots/26_focus_return_overview.png)

### 30 Stress 1Room Idle

**Stress — 1 Room Idle**: Single team, single agent. Smallest valid config.

![Stress — 1 Room Idle](screenshots/30_stress_1room_idle.png)

### 31 Stress 1Room Active

**Stress — 1 Room Active**: Single agent running in single-room layout.

![Stress — 1 Room Active](screenshots/31_stress_1room_active.png)

### 32 Stress 1Room Complete

**Stress — 1 Room Complete**: Single agent completed. Clean final state.

![Stress — 1 Room Complete](screenshots/32_stress_1room_complete.png)

### 33 Stress 10Agents Idle

**Stress — 10 Agents Idle**: 10 agents in one room at idle. Overflow icons visible for agents beyond desk capacity.

![Stress — 10 Agents Idle](screenshots/33_stress_10agents_idle.png)

### 34 Stress 10Agents Active

**Stress — 10 Agents Active**: All 10 agents activated simultaneously. Overflow icons glow.

![Stress — 10 Agents Active](screenshots/34_stress_10agents_active.png)

### 35 Stress 10Agents Complete

**Stress — 10 Agents Complete**: All 10 agents completed.

![Stress — 10 Agents Complete](screenshots/35_stress_10agents_complete.png)

### 36 Stress 6Rooms Default

**Stress — 6 Rooms Default**: 6-team grid before fit view. May show clipping at default zoom.

![Stress — 6 Rooms Default](screenshots/36_stress_6rooms_default.png)

### 37 Stress 6Rooms Fit

**Stress — 6 Rooms Fit**: Fit view with 6 rooms — all rooms must be fully visible (baseZoom floor fix).

![Stress — 6 Rooms Fit](screenshots/37_stress_6rooms_fit.png)

### 38 Stress 6Rooms Active

**Stress — 6 Rooms Active**: All 12 agents active across 6 rooms simultaneously.

![Stress — 6 Rooms Active](screenshots/38_stress_6rooms_active.png)

### 39 Stress 6Rooms Complete

**Stress — 6 Rooms Complete**: All agents completed across full 6-room grid.

![Stress — 6 Rooms Complete](screenshots/39_stress_6rooms_complete.png)
