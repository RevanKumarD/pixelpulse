---
name: pixelpulse-status
description: Use when the user asks about session progress, token usage, costs,
  tool patterns, subagent activity, or session efficiency. Also use when reflecting
  on what work has been done in the current session.
---

# PixelPulse Session Status

You have access to real-time observability data about your current session via the
pixelpulse MCP tools. Use them to answer questions about:

- **Cost**: "How much have I spent?" → use `pixelpulse_session_stats` or `pixelpulse_cost_breakdown`
- **Activity**: "What tools have I used most?" → use `pixelpulse_tool_summary`
- **Subagents**: "What are my subagents doing?" → use `pixelpulse_subagent_tree`
- **Events**: "What happened recently?" → use `pixelpulse_recent_events`
- **Dashboard**: "Where can I see the dashboard?" → use `pixelpulse_dashboard_url`

## Reporting Guidelines

When reporting costs, always include both token counts and dollar amounts.
When reporting subagent status, include the agent type and current status.
Format cost as USD with 4 decimal places (e.g., $0.0612).
Format token counts with comma separators (e.g., 12,450 tokens).
