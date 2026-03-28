"""Claude Code + PixelPulse — Visualize Claude Code sessions in real-time.

This example shows two ways to use PixelPulse with Claude Code:

1. **Live hooks**: Configure Claude Code to POST events to PixelPulse's
   hook receiver endpoint. Events appear on the dashboard in real-time.

2. **Transcript replay**: Parse a saved `.jsonl` transcript file and
   replay all events into the dashboard.

Quick Start (Live Hooks):

    1. Run this script:
       $ python examples/claude_code_example.py

    2. Copy the generated hooks config into your .claude/settings.json

    3. Open http://localhost:8765 in your browser

    4. Use Claude Code normally — tool calls, thinking, and costs will
       appear on the pixel-art dashboard in real-time!

Quick Start (Transcript Replay):

    $ python examples/claude_code_example.py --replay /path/to/transcript.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser(description="PixelPulse + Claude Code")
    parser.add_argument(
        "--replay",
        type=str,
        default=None,
        help="Path to a Claude Code .jsonl transcript to replay",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for the dashboard (default: 8765)",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run a simulated Claude Code session for demo purposes",
    )
    args = parser.parse_args()

    from pixelpulse import PixelPulse

    # Configure PixelPulse with a Claude Code agent
    pp = PixelPulse(
        agents={
            "claude": {
                "team": "coding",
                "role": "AI coding assistant",
            },
        },
        teams={
            "coding": {
                "label": "Claude Code",
                "color": "#cc785c",
            },
        },
        title="PixelPulse — Claude Code",
        port=args.port,
    )

    adapter = pp.adapter("claude_code")

    if args.replay:
        # Replay mode: parse transcript file
        print(f"\n[REPLAY] Replaying transcript: {args.replay}")
        print(f"         Dashboard: http://localhost:{args.port}\n")
        import threading
        server_thread = threading.Thread(
            target=pp.serve,
            kwargs={"port": args.port, "open_browser": True},
            daemon=True,
        )
        server_thread.start()
        time.sleep(2)  # Wait for server to start
        adapter.replay_transcript(args.replay)
        print("\n[DONE] Replay complete! Dashboard will stay open.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    elif args.simulate:
        # Simulation mode: fake a Claude Code session
        print(f"\n[SIM] Running Claude Code simulation")
        print(f"      Dashboard: http://localhost:{args.port}\n")
        import threading
        server_thread = threading.Thread(
            target=pp.serve,
            kwargs={"port": args.port, "open_browser": True},
            daemon=True,
        )
        server_thread.start()
        time.sleep(2)

        _run_simulation(adapter)

        print("\n[DONE] Simulation complete!")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    else:
        # Live mode: start server with hook endpoint
        hooks_config = adapter.generate_hooks_config(port=args.port)

        print(f"\n[LIVE] PixelPulse Claude Code Hook Receiver")
        print(f"       Dashboard: http://localhost:{args.port}")
        print(f"       Hook endpoint: http://localhost:{args.port}/hooks/claude-code")
        print(f"\nAdd this to your .claude/settings.json:\n")
        print(json.dumps(hooks_config, indent=2))
        print(f"\n   Then use Claude Code normally — events will appear on the dashboard!\n")

        pp.serve(port=args.port, open_browser=True)


def _run_simulation(adapter) -> None:
    """Simulate a typical Claude Code session for demo purposes."""

    # Session starts
    adapter.on_hook_event({
        "hook_event_name": "SessionStart",
        "session_id": "demo-session-1",
    })
    time.sleep(1)

    # User asks to fix a bug
    # Claude reads the file
    adapter.on_hook_event({
        "hook_event_name": "PreToolUse",
        "session_id": "demo-session-1",
        "tool_name": "Read",
        "tool_input": {"file_path": "src/auth/login.py"},
    })
    time.sleep(0.5)
    adapter.on_hook_event({
        "hook_event_name": "PostToolUse",
        "session_id": "demo-session-1",
        "tool_name": "Read",
        "tool_response": "class LoginHandler:\n    def authenticate(self, user, password):\n        ...",
    })
    time.sleep(1)

    # Claude searches for related code
    adapter.on_hook_event({
        "hook_event_name": "PreToolUse",
        "session_id": "demo-session-1",
        "tool_name": "Grep",
        "tool_input": {"pattern": "authenticate", "path": "src/"},
    })
    time.sleep(0.3)
    adapter.on_hook_event({
        "hook_event_name": "PostToolUse",
        "session_id": "demo-session-1",
        "tool_name": "Grep",
        "tool_response": "src/auth/login.py:15\nsrc/auth/oauth.py:42\nsrc/middleware/auth.py:8",
    })
    time.sleep(1)

    # Claude runs the tests
    adapter.on_hook_event({
        "hook_event_name": "PreToolUse",
        "session_id": "demo-session-1",
        "tool_name": "Bash",
        "tool_input": {"command": "python -m pytest tests/auth/ -v"},
    })
    time.sleep(2)
    adapter.on_hook_event({
        "hook_event_name": "PostToolUse",
        "session_id": "demo-session-1",
        "tool_name": "Bash",
        "tool_response": "tests/auth/test_login.py::test_valid_login PASSED\ntests/auth/test_login.py::test_invalid_password FAILED",
    })
    time.sleep(1)

    # Claude edits the file
    adapter.on_hook_event({
        "hook_event_name": "PreToolUse",
        "session_id": "demo-session-1",
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "src/auth/login.py",
            "old_string": "if password == stored_hash:",
            "new_string": "if verify_password(password, stored_hash):",
        },
    })
    time.sleep(0.5)
    adapter.on_hook_event({
        "hook_event_name": "PostToolUse",
        "session_id": "demo-session-1",
        "tool_name": "Edit",
        "tool_response": "File edited successfully",
    })
    time.sleep(1)

    # Claude spawns a subagent for broader search
    adapter.on_hook_event({
        "hook_event_name": "SubagentStart",
        "session_id": "demo-session-1",
        "subagent_type": "Explore",
        "description": "Search for other password comparison patterns",
    })
    time.sleep(3)
    adapter.on_hook_event({
        "hook_event_name": "SubagentStop",
        "session_id": "demo-session-1",
        "agent_transcript_path": "/tmp/subagent-transcript.jsonl",
    })
    time.sleep(1)

    # Claude runs tests again
    adapter.on_hook_event({
        "hook_event_name": "PreToolUse",
        "session_id": "demo-session-1",
        "tool_name": "Bash",
        "tool_input": {"command": "python -m pytest tests/auth/ -v"},
    })
    time.sleep(2)
    adapter.on_hook_event({
        "hook_event_name": "PostToolUse",
        "session_id": "demo-session-1",
        "tool_name": "Bash",
        "tool_response": "tests/auth/test_login.py::test_valid_login PASSED\ntests/auth/test_login.py::test_invalid_password PASSED\n\n2 passed in 0.3s",
    })
    time.sleep(1)

    # Token usage from the stop event
    adapter.on_hook_event({
        "hook_event_name": "Stop",
        "session_id": "demo-session-1",
        "last_assistant_message": {
            "usage": {"input_tokens": 4200, "output_tokens": 1800},
            "model": "claude-sonnet-4-20250514",
        },
    })
    time.sleep(1)

    # Session ends
    adapter.on_hook_event({
        "hook_event_name": "SessionEnd",
        "session_id": "demo-session-1",
    })


if __name__ == "__main__":
    main()
