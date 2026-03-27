"""Generic adapter — for custom agent systems without a specific framework.

This adapter simply exposes the PixelPulse instance's emission methods.
Users call them manually from their agent code.
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse


class GenericAdapter:
    """Pass-through adapter for manual event emission.

    Usage::

        pp = PixelPulse(agents={...})
        adapter = pp.adapter("generic")

        # In your agent code:
        adapter.pp.agent_started("my-agent", task="doing stuff")
        adapter.pp.agent_completed("my-agent", output="done!")
    """

    def __init__(self, pp: PixelPulse) -> None:
        self.pp = pp

    def instrument(self, target: Any) -> None:
        """No-op for generic adapter — instrumentation is manual."""
        pass

    def detach(self) -> None:
        """No-op for generic adapter."""
        pass
