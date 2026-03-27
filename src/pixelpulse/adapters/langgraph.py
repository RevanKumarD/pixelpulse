"""LangGraph adapter — hooks into LangGraph's callback system.

Translates LangGraph node execution, tool calls, and state transitions
into PixelPulse events.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

logger = logging.getLogger(__name__)


class LangGraphAdapter:
    """Adapter for LangGraph/LangChain agent framework.

    Usage::

        from langgraph.graph import StateGraph
        from pixelpulse import PixelPulse

        pp = PixelPulse(agents={...})
        adapter = pp.adapter("langgraph")
        adapter.instrument(my_graph)
    """

    def __init__(self, pp: PixelPulse) -> None:
        self._pp = pp
        self._graph = None

    def instrument(self, graph: Any) -> None:
        """Attach to a LangGraph StateGraph or compiled graph.

        Uses LangGraph's callback mechanism to capture node execution
        events and translate them to PixelPulse events.
        """
        self._graph = graph
        logger.info("LangGraph adapter instrumented (callback-based)")
        # TODO: Implement LangGraph callback integration
        # LangGraph uses LangChain callbacks — register a custom handler
        # that translates on_chain_start, on_chain_end, on_tool_start, etc.

    def detach(self) -> None:
        self._graph = None

    def create_callbacks(self) -> list:
        """Return a list of LangChain-compatible callbacks for manual injection.

        Use this if auto-instrumentation doesn't work::

            graph.invoke(inputs, config={"callbacks": adapter.create_callbacks()})
        """
        # TODO: Return a LangChain BaseCallbackHandler subclass
        return []
