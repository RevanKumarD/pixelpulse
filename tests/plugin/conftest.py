"""Shared fixtures for plugin tests."""
from __future__ import annotations

import json


def make_hook_payload(
    hook_event_name: str,
    session_id: str = "test-session-001",
    **extra: object,
) -> str:
    """Build a JSON string mimicking Claude Code hook stdin."""
    payload = {"hook_event_name": hook_event_name, "session_id": session_id, **extra}
    return json.dumps(payload)
