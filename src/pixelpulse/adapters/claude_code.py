"""Claude Code adapter — observes Claude Code sessions via its hooks system.

Claude Code exposes a lifecycle hooks API in ``.claude/settings.json``.
This adapter sets up HTTP hooks that point at a local PixelPulse endpoint,
translating tool calls, thinking, and session events into PixelPulse events.

Two usage modes:

1. **HTTP hooks (recommended)**: PixelPulse runs a hook receiver endpoint.
   Configure Claude Code to POST to it on PreToolUse, PostToolUse, etc.

2. **Transcript replay**: Parse a ``.jsonl`` transcript file after a session
   ends, replaying all events into the dashboard.

Requires: ``pip install pixelpulse`` (no extra dependencies)
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

logger = logging.getLogger(__name__)

# Tool categories for grouping in the dashboard
_TOOL_CATEGORIES: dict[str, str] = {
    "Read": "file_read",
    "Write": "file_write",
    "Edit": "file_edit",
    "Bash": "command",
    "Glob": "file_search",
    "Grep": "content_search",
    "Agent": "subagent",
    "WebFetch": "web",
    "WebSearch": "web",
}

# Approximate token costs for Claude models
# Per-million-token pricing (input, output) — March 2026
# Sources: docs.anthropic.com/en/docs/about-claude/pricing
_TOKEN_COSTS_MTK: dict[str, tuple[float, float]] = {
    # Claude 4.5/4.6 family
    "claude-opus-4":   (5.0, 25.0),     # Opus 4.5 & 4.6
    "claude-sonnet-4": (3.0, 15.0),     # Sonnet 4.5 & 4.6
    "claude-haiku-4":  (1.0, 5.0),      # Haiku 4.5
    # Claude 3.5 family
    "claude-3.5-sonnet": (3.0, 15.0),
    "claude-3.5-haiku":  (0.80, 4.0),
    # Claude 3 family
    "claude-3-opus":   (15.0, 75.0),
    "claude-3-sonnet": (3.0, 15.0),
    "claude-3-haiku":  (0.25, 1.25),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost from token counts and model name.

    Pricing is per million tokens. We match model ID by prefix so that
    'claude-opus-4-6-20260301' matches 'claude-opus-4'.
    """
    for prefix, (in_mtk, out_mtk) in _TOKEN_COSTS_MTK.items():
        if model and model.startswith(prefix):
            return (input_tokens / 1_000_000 * in_mtk) + (output_tokens / 1_000_000 * out_mtk)
    # Unknown model — fall back to Sonnet 4.6 pricing ($3/$15 per MTok)
    return (input_tokens / 1_000_000 * 3.0) + (output_tokens / 1_000_000 * 15.0)


def _sanitize_tool_name(name: str) -> str:
    """Convert a tool name to a dashboard-friendly format."""
    if not name:
        return "unknown-tool"
    # MCP tools come as mcp__server__tool
    if name.startswith("mcp__"):
        parts = name.split("__")
        return f"mcp:{parts[1]}:{parts[2]}" if len(parts) >= 3 else name
    return name.lower().replace(" ", "-")


class ClaudeCodeAdapter:
    """Adapter for Claude Code sessions.

    Usage (HTTP hooks)::

        from pixelpulse import PixelPulse

        pp = PixelPulse(
            agents={"claude": {"team": "coding", "role": "AI coding assistant"}},
            teams={"coding": {"label": "Claude Code", "color": "#cc785c"}},
        )
        adapter = pp.adapter("claude_code")

        # Generate hooks config to paste into .claude/settings.json
        hooks_config = adapter.generate_hooks_config(port=8765)
        print(json.dumps(hooks_config, indent=2))

        # Start the dashboard (includes hook receiver endpoint)
        pp.serve(port=8765)

    Usage (transcript replay)::

        adapter = pp.adapter("claude_code")
        adapter.replay_transcript("/path/to/transcript.jsonl")
    """

    def __init__(self, pp: PixelPulse) -> None:
        self._pp = pp
        self._session_id: str | None = None
        self._run_counter: int = 0
        self._current_run_id: str = ""
        self._tool_start_times: dict[str, float] = {}
        self._accumulated_cost: float = 0.0
        self._tool_count: int = 0
        self._agent_name: str = "claude"
        self._active: bool = False

    def instrument(self, target: Any = None) -> None:
        """Mark the adapter as active.

        For Claude Code, there's no target to instrument — the hooks
        system does the instrumentation externally. This just marks the
        adapter as ready to receive hook events.

        Args:
            target: Ignored. Accepted for protocol compatibility.
        """
        self._active = True
        # Determine agent name from PixelPulse config
        agents = list(self._pp._agents.keys())
        if agents:
            self._agent_name = agents[0]
        logger.info("Claude Code adapter activated (agent: %s)", self._agent_name)

    def detach(self) -> None:
        """Deactivate the adapter."""
        if self._current_run_id:
            self._pp.run_completed(
                self._current_run_id,
                status="completed",
                total_cost=self._accumulated_cost,
            )
        self._active = False
        self._session_id = None
        self._tool_start_times.clear()
        self._accumulated_cost = 0.0

    # ---- Hook Event Handlers ----

    def on_hook_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Process an incoming hook event from Claude Code.

        This is the main entry point called by the PixelPulse HTTP endpoint
        when a Claude Code hook fires.

        Args:
            event: The hook event payload (JSON parsed from stdin).

        Returns:
            Response dict for Claude Code (always ``{"continue": true}``).
        """
        if not self._active:
            self.instrument()

        hook_name = event.get("hook_event_name", "")
        session_id = event.get("session_id", "")

        # Start a new run if session changed
        if session_id and session_id != self._session_id:
            self._start_session(session_id)

        handler = {
            "SessionStart": self._on_session_start,
            "PreToolUse": self._on_pre_tool_use,
            "PostToolUse": self._on_post_tool_use,
            "SubagentStart": self._on_subagent_start,
            "SubagentStop": self._on_subagent_stop,
            "Stop": self._on_stop,
            "SessionEnd": self._on_session_end,
        }.get(hook_name)

        if handler:
            handler(event)

        return {"continue": True}

    def _start_session(self, session_id: str) -> None:
        """Initialize a new Claude Code session as a PixelPulse run."""
        # End previous session if any
        if self._current_run_id:
            self._pp.run_completed(
                self._current_run_id,
                status="completed",
                total_cost=self._accumulated_cost,
            )

        self._session_id = session_id
        self._run_counter += 1
        self._current_run_id = f"claude-code-{self._run_counter}"
        self._accumulated_cost = 0.0
        self._tool_count = 0
        self._tool_start_times.clear()

        self._pp.run_started(
            self._current_run_id,
            name=f"Claude Code Session #{self._run_counter}",
        )
        self._pp.agent_started(self._agent_name, task="Claude Code session")

    def _on_session_start(self, event: dict[str, Any]) -> None:
        """Handle SessionStart hook."""
        session_id = event.get("session_id", f"session-{time.monotonic()}")
        if not self._session_id:
            self._start_session(session_id)

    def _on_pre_tool_use(self, event: dict[str, Any]) -> None:
        """Handle PreToolUse hook — tool call is about to execute."""
        tool_name = event.get("tool_name", "unknown")
        tool_input = event.get("tool_input", {})
        tool_id = f"{tool_name}-{self._tool_count}"
        self._tool_count += 1

        self._tool_start_times[tool_id] = time.monotonic()

        # Emit thinking event with tool info
        input_preview = ""
        if isinstance(tool_input, dict):
            # Show relevant field based on tool type
            if tool_name == "Bash":
                input_preview = tool_input.get("command", "")[:150]
            elif tool_name in ("Read", "Write", "Edit"):
                input_preview = tool_input.get("file_path", "")[:150]
            elif tool_name == "Grep":
                input_preview = tool_input.get("pattern", "")[:100]
            elif tool_name == "Glob":
                input_preview = tool_input.get("pattern", "")[:100]
            elif tool_name == "Agent":
                input_preview = tool_input.get("description", "")[:150]
            else:
                input_preview = json.dumps(tool_input)[:150]

        display_name = _sanitize_tool_name(tool_name)
        thought = (
            f"Using {display_name}: {input_preview}" if input_preview else f"Using {display_name}"
        )
        self._pp.agent_thinking(self._agent_name, thought=thought)

    def _on_post_tool_use(self, event: dict[str, Any]) -> None:
        """Handle PostToolUse hook — tool call completed."""
        tool_name = event.get("tool_name", "unknown")
        tool_response = event.get("tool_response", "")

        # Compute duration
        tool_id = f"{tool_name}-{self._tool_count - 1}"
        start = self._tool_start_times.pop(tool_id, None)
        _ = int((time.monotonic() - start) * 1000) if start else 0

        # Emit artifact for meaningful tool results
        category = _TOOL_CATEGORIES.get(tool_name, "tool")
        if tool_response:
            response_preview = str(tool_response)[:300]
            self._pp.artifact_created(
                self._agent_name,
                artifact_type=f"{category}_result",
                content=f"{tool_name}: {response_preview}",
            )

    def _on_subagent_start(self, event: dict[str, Any]) -> None:
        """Handle SubagentStart hook — a subagent was spawned."""
        agent_type = event.get("subagent_type", "subagent")
        description = event.get("description", "Subagent task")

        self._pp.agent_thinking(
            self._agent_name,
            thought=f"Spawning subagent ({agent_type}): {description[:150]}",
        )

    def _on_subagent_stop(self, event: dict[str, Any]) -> None:
        """Handle SubagentStop hook — a subagent finished.

        If transcript_path is available, we could replay it for detailed
        sub-span visibility. For now, emit a completion artifact.
        """
        transcript_path = event.get("agent_transcript_path", "")
        if transcript_path:
            self._pp.artifact_created(
                self._agent_name,
                artifact_type="subagent_transcript",
                content=f"Subagent transcript: {transcript_path}",
            )

    def _on_stop(self, event: dict[str, Any]) -> None:
        """Handle Stop hook — Claude finished a response.

        This is where we can extract token usage from the assistant message
        metadata if available.
        """
        message = event.get("last_assistant_message", "")
        if isinstance(message, dict):
            # Extract usage if present
            usage = message.get("usage", {})
            if usage:
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                model = message.get("model", "claude-sonnet-4")
                cost = _estimate_cost(model, input_tokens, output_tokens)
                self._accumulated_cost += cost
                self._pp.cost_update(
                    self._agent_name,
                    cost=cost,
                    tokens_in=input_tokens,
                    tokens_out=output_tokens,
                    model=model,
                )

    def _on_session_end(self, event: dict[str, Any]) -> None:
        """Handle SessionEnd hook — session is closing."""
        if self._current_run_id:
            self._pp.agent_completed(
                self._agent_name,
                output=(
                    f"Session complete ({self._tool_count} tool calls,"
                    f" ${self._accumulated_cost:.4f})"
                ),
            )
            self._pp.run_completed(
                self._current_run_id,
                status="completed",
                total_cost=self._accumulated_cost,
            )
            self._current_run_id = ""

    # ---- Hooks Config Generator ----

    def generate_hooks_config(self, port: int = 8765) -> dict[str, Any]:
        """Generate Claude Code hooks configuration.

        Returns a dict to merge into ``.claude/settings.json`` that
        configures Claude Code to POST events to PixelPulse's hook
        receiver endpoint.

        Args:
            port: The port PixelPulse is serving on.

        Returns:
            Dict with ``hooks`` key ready for ``.claude/settings.json``.
        """
        base_url = f"http://localhost:{port}/hooks/claude-code"
        return {
            "hooks": {
                "SessionStart": [
                    {
                        "type": "http",
                        "url": base_url,
                        "timeout": 5000,
                    }
                ],
                "PreToolUse": [
                    {
                        "type": "http",
                        "url": base_url,
                        "timeout": 5000,
                    }
                ],
                "PostToolUse": [
                    {
                        "type": "http",
                        "url": base_url,
                        "timeout": 5000,
                    }
                ],
                "SubagentStart": [
                    {
                        "type": "http",
                        "url": base_url,
                        "timeout": 5000,
                    }
                ],
                "SubagentStop": [
                    {
                        "type": "http",
                        "url": base_url,
                        "timeout": 5000,
                    }
                ],
                "Stop": [
                    {
                        "type": "http",
                        "url": base_url,
                        "timeout": 5000,
                    }
                ],
                "SessionEnd": [
                    {
                        "type": "http",
                        "url": base_url,
                        "timeout": 5000,
                    }
                ],
            }
        }

    # ---- Transcript Replay ----

    def replay_transcript(self, transcript_path: str | Path) -> None:
        """Replay a Claude Code transcript file into the dashboard.

        Reads a ``.jsonl`` file (as provided in hook events' ``transcript_path``
        field) and emits PixelPulse events for each entry.

        Args:
            transcript_path: Path to the ``.jsonl`` transcript file.
        """
        path = Path(transcript_path)
        if not path.exists():
            logger.error("Transcript file not found: %s", path)
            return

        self.instrument()
        self._start_session(f"replay-{path.stem}")

        with path.open() as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Skipping invalid JSON at line %d", line_num)
                    continue

                self._replay_entry(entry)

        # End the replay session
        self._pp.agent_completed(
            self._agent_name,
            output=f"Transcript replay complete ({self._tool_count} tool calls)",
        )
        self._pp.run_completed(
            self._current_run_id,
            status="completed",
            total_cost=self._accumulated_cost,
        )
        self._current_run_id = ""

    def _replay_entry(self, entry: dict[str, Any]) -> None:
        """Process a single transcript entry during replay."""
        role = entry.get("role", "")
        if role == "assistant":
            # Assistant message — may contain tool_use blocks
            content = entry.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type", "")
                        if block_type == "tool_use":
                            self._tool_count += 1
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})
                            display_name = _sanitize_tool_name(tool_name)
                            input_str = json.dumps(tool_input)[:150] if tool_input else ""
                            self._pp.agent_thinking(
                                self._agent_name,
                                thought=f"Using {display_name}: {input_str}",
                            )
                        elif block_type == "text":
                            text = block.get("text", "")
                            if text:
                                self._pp.agent_thinking(
                                    self._agent_name,
                                    thought=text[:300],
                                )

            # Extract usage from assistant message
            usage = entry.get("usage", {})
            if usage:
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                model = entry.get("model", "claude-sonnet-4")
                cost = _estimate_cost(model, input_tokens, output_tokens)
                self._accumulated_cost += cost
                self._pp.cost_update(
                    self._agent_name,
                    cost=cost,
                    tokens_in=input_tokens,
                    tokens_out=output_tokens,
                    model=model,
                )

        elif role == "tool":
            # Tool result
            content = entry.get("content", "")
            if content:
                content_str = str(content)[:300] if not isinstance(content, str) else content[:300]
                self._pp.artifact_created(
                    self._agent_name,
                    artifact_type="tool_result",
                    content=content_str,
                )
