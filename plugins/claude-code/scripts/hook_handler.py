#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""PixelPulse hook handler for Claude Code.

Reads a hook event from stdin (JSON), POSTs it to the PixelPulse server,
and writes {"continue": true} to stdout.

On SessionStart, also ensures the PixelPulse server is running.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def parse_stdin(raw: str) -> dict | None:
    """Parse JSON hook payload from stdin."""
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw.strip())
    except (json.JSONDecodeError, TypeError):
        return None


def build_response() -> dict:
    """Build the standard Claude Code hook response."""
    return {"continue": True}


def should_ensure_server(hook_event_name: str) -> bool:
    """Return True if this event should trigger server start."""
    return hook_event_name == "SessionStart"


def get_server_url(port: int = 8765) -> str:
    """Build the PixelPulse hook endpoint URL."""
    return f"http://localhost:{port}/hooks/claude-code"


def get_port() -> int:
    """Read port from env (plugin userConfig) or default."""
    return int(os.environ.get("PIXELPULSE_PORT", "8765"))


def ensure_server(port: int) -> None:
    """Start the PixelPulse server if not already running."""
    script_dir = Path(__file__).resolve().parent
    ensure_script = script_dir / "ensure_server.py"
    if ensure_script.exists():
        subprocess.Popen(
            [sys.executable, str(ensure_script), "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def post_event(url: str, payload: dict) -> None:
    """POST the hook event to PixelPulse. Fire-and-forget — don't block Claude."""
    try:
        import httpx

        with httpx.Client(timeout=3.0) as client:
            client.post(url, json=payload)
    except Exception:
        pass  # Graceful degradation: hooks continue even if server is down


def main() -> None:
    raw_input = sys.stdin.read()
    event = parse_stdin(raw_input)

    if event is None:
        # Invalid input — still respond so Claude Code continues
        print(json.dumps(build_response()))
        return

    port = get_port()
    hook_name = event.get("hook_event_name", "")

    # On SessionStart, ensure the server is running
    if should_ensure_server(hook_name):
        ensure_server(port)

    # Forward the event to the PixelPulse server
    url = get_server_url(port)
    post_event(url, event)

    # Always respond with continue: true
    print(json.dumps(build_response()))


if __name__ == "__main__":
    main()
