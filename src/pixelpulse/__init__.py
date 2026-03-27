"""PixelPulse — Real-time pixel-art dashboard for multi-agent systems.

Quick start::

    from pixelpulse import PixelPulse

    pp = PixelPulse(
        agents={
            "researcher": {"team": "research", "role": "Finds information"},
            "writer": {"team": "content", "role": "Writes articles"},
        },
        teams={
            "research": {"label": "Research", "color": "#00d4ff"},
            "content": {"label": "Content", "color": "#ff6ec7"},
        },
    )
    pp.serve(port=8765)
"""
from __future__ import annotations

__version__ = "0.1.0"

from pixelpulse.config import AgentConfig, TeamConfig
from pixelpulse.core import PixelPulse
from pixelpulse.protocol import create_event, validate_event

__all__ = [
    "PixelPulse",
    "AgentConfig",
    "TeamConfig",
    "create_event",
    "validate_event",
    "__version__",
]
