# PixelPulse Visual Test Report

> Generated: 2026-03-27 13:00:54
> Tests: 5 scenarios, 20 screenshots
> Model: gpt-4o-mini (cheapest available)

## Test Results

| # | Test | Status |
|---|------|--------|
| 1 | Demo Mode + Dynamic Canvas | PASS |
| 2 | LangGraph Adapter (Real OpenAI) | PASS |
| 3 | @observe Decorator (Real OpenAI) | PASS |
| 4 | OTEL Ingestion | PASS |
| 5 | Manual Events (Generic) | PASS |

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
