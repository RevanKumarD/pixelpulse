#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.0.0", "httpx"]
# ///
"""PixelPulse MCP server — exposes session metrics as Claude Code tools.

Tools:
  - pixelpulse_session_stats: Current session cost/token/tool metrics
  - pixelpulse_cost_breakdown: Per-model cost breakdown
  - pixelpulse_subagent_tree: Tree of spawned subagents
  - pixelpulse_tool_summary: Tool usage frequency
  - pixelpulse_recent_events: Last N session events
  - pixelpulse_dashboard_url: Dashboard URL and status
"""
from __future__ import annotations

import os
import re
from collections import defaultdict

import httpx

# ---- Configuration ----

PORT = int(os.environ.get("PIXELPULSE_PORT", "8765"))
BASE_URL = f"http://localhost:{PORT}"


# ---- Aggregation functions (pure, testable) ----


def _is_tool_call(event: dict) -> bool:
    """Check if an event represents a tool call (thinking with 'Using ' prefix)."""
    if event.get("type") != "agent_status":
        return False
    payload = event.get("payload", {})
    thought = payload.get("thought", "")
    return payload.get("status") == "thinking" and thought.startswith("Using ")


def _extract_tool_name(thought: str) -> str:
    """Extract tool name from a 'Using <tool>: ...' thought string."""
    match = re.match(r"Using ([^:]+)", thought)
    return match.group(1).strip().lower() if match else "unknown"


def aggregate_session_stats(events: list[dict]) -> dict:
    """Aggregate session-level statistics from dashboard events."""
    total_cost = 0.0
    tokens_in = 0
    tokens_out = 0
    tool_calls = 0
    agents_seen: set[str] = set()
    main_agent = None

    for event in events:
        etype = event.get("type", "")
        payload = event.get("payload", {})

        if etype == "cost_update":
            total_cost += payload.get("cost", 0)
            tokens_in += payload.get("tokens_in", 0)
            tokens_out += payload.get("tokens_out", 0)

        if etype == "agent_status":
            agent = payload.get("agent", "")
            if agent:
                if main_agent is None:
                    main_agent = agent
                agents_seen.add(agent)

        if _is_tool_call(event):
            tool_calls += 1

    subagents = agents_seen - {main_agent} if main_agent else set()

    return {
        "tool_calls": tool_calls,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost": round(total_cost, 6),
        "subagents_spawned": len(subagents),
    }


def aggregate_cost_breakdown(events: list[dict]) -> list[dict]:
    """Group cost events by model."""
    models: dict[str, dict] = defaultdict(
        lambda: {"tokens_in": 0, "tokens_out": 0, "cost": 0.0, "calls": 0}
    )

    for event in events:
        if event.get("type") != "cost_update":
            continue
        payload = event.get("payload", {})
        model = payload.get("model", "unknown")
        models[model]["tokens_in"] += payload.get("tokens_in", 0)
        models[model]["tokens_out"] += payload.get("tokens_out", 0)
        models[model]["cost"] += payload.get("cost", 0)
        models[model]["calls"] += 1

    return [
        {"model": model, **data}
        for model, data in sorted(models.items(), key=lambda x: -x[1]["cost"])
    ]


def aggregate_tool_summary(events: list[dict]) -> list[dict]:
    """Count tool usage from thinking events."""
    tools: dict[str, int] = defaultdict(int)

    for event in events:
        if not _is_tool_call(event):
            continue
        thought = event.get("payload", {}).get("thought", "")
        tool_name = _extract_tool_name(thought)
        tools[tool_name] += 1

    return [
        {"tool": tool, "count": count}
        for tool, count in sorted(tools.items(), key=lambda x: -x[1])
    ]


def build_subagent_tree(events: list[dict]) -> dict:
    """Build a tree of agents from status events."""
    agents: dict[str, dict] = {}
    first_agent = None

    for event in events:
        if event.get("type") != "agent_status":
            continue
        payload = event.get("payload", {})
        agent = payload.get("agent", "")
        if not agent:
            continue
        if first_agent is None:
            first_agent = agent
        status = payload.get("status", "unknown")
        if agent not in agents:
            agents[agent] = {"id": agent, "status": status, "children": []}
        else:
            agents[agent]["status"] = status

    if not agents:
        return {"id": "unknown", "status": "idle", "children": []}

    main = first_agent or "unknown"
    root = agents.get(main, {"id": main, "status": "idle", "children": []})
    root["children"] = [
        data for agent_id, data in agents.items() if agent_id != main
    ]
    return root


def get_recent_events(events: list[dict], n: int = 20) -> list[dict]:
    """Return the last N events."""
    return events[-n:]


# ---- HTTP helpers ----


def _fetch_events() -> list[dict]:
    """Fetch current events from PixelPulse server."""
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{BASE_URL}/api/events")
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return []


def _check_health() -> dict:
    """Check if PixelPulse server is running."""
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{BASE_URL}/api/health")
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return {"status": "unreachable"}


# ---- MCP Tools (only registered when run as MCP server) ----

if __name__ == "__main__":
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("pixelpulse")

    @mcp.tool()
    def pixelpulse_session_stats() -> dict:
        """Get current session metrics: tool calls, tokens, cost, subagents."""
        events = _fetch_events()
        return aggregate_session_stats(events)

    @mcp.tool()
    def pixelpulse_cost_breakdown() -> list[dict]:
        """Get per-model token costs for the current session."""
        events = _fetch_events()
        return aggregate_cost_breakdown(events)

    @mcp.tool()
    def pixelpulse_subagent_tree() -> dict:
        """Get the tree of all spawned subagents and their status."""
        events = _fetch_events()
        return build_subagent_tree(events)

    @mcp.tool()
    def pixelpulse_tool_summary() -> list[dict]:
        """Get tool usage frequency for the current session."""
        events = _fetch_events()
        return aggregate_tool_summary(events)

    @mcp.tool()
    def pixelpulse_recent_events(n: int = 20) -> list[dict]:
        """Get the last N events from the current session."""
        events = _fetch_events()
        return get_recent_events(events, n=n)

    @mcp.tool()
    def pixelpulse_dashboard_url() -> dict:
        """Get the URL and status of the running PixelPulse dashboard."""
        health = _check_health()
        return {
            "url": f"{BASE_URL}",
            "status": health.get("status", "unreachable"),
        }

    mcp.run()
