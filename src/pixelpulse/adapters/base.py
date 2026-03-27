"""Base adapter protocol for framework integrations."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BaseAdapter(Protocol):
    """Protocol that all framework adapters must implement.

    Adapters hook into a framework's event/callback system and translate
    framework-specific events into PixelPulse protocol events.
    """

    def instrument(self, target: Any) -> None:
        """Attach instrumentation to a framework object (crew, graph, etc.)."""
        ...

    def detach(self) -> None:
        """Remove instrumentation and clean up."""
        ...
