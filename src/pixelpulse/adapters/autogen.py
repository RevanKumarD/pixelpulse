"""AutoGen adapter — leverages AutoGen's native OpenTelemetry tracing.

AutoGen has built-in support for tracing powered by OpenTelemetry.
This adapter configures AutoGen to export traces and translates
OTel spans into PixelPulse events.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

logger = logging.getLogger(__name__)


class AutoGenAdapter:
    """Adapter for Microsoft AutoGen agent framework.

    Usage::

        from autogen_agentchat import AssistantAgent
        from pixelpulse import PixelPulse

        pp = PixelPulse(agents={...})
        adapter = pp.adapter("autogen")
        adapter.instrument(runtime)
    """

    def __init__(self, pp: PixelPulse) -> None:
        self._pp = pp

    def instrument(self, runtime: Any) -> None:
        """Attach to an AutoGen runtime.

        AutoGen is already OTel-native, so this adapter configures
        the OTel exporter to send spans to PixelPulse.
        """
        logger.info("AutoGen adapter instrumented (OTel-based)")
        # TODO: Configure AutoGen's OTel tracing to export to PixelPulse
        # AutoGen uses opentelemetry-api/sdk — register a SpanProcessor
        # that translates spans to PixelPulse events

    def detach(self) -> None:
        pass
