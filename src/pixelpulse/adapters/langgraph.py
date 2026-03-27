"""LangGraph adapter — hooks into LangGraph's callback system.

Translates LangGraph node execution, tool calls, and state transitions
into PixelPulse events.  LangGraph is built on LangChain and uses its
callback infrastructure.  This adapter provides:

1. A ``PixelPulseCallbackHandler`` (a LangChain ``BaseCallbackHandler``
   subclass) that converts LangChain lifecycle events into PixelPulse
   ``agent_started``, ``agent_completed``, ``agent_thinking``, etc.

2. ``LangGraphAdapter.instrument()`` — patches a compiled graph's
   ``invoke`` / ``ainvoke`` so callbacks are injected automatically.

3. ``LangGraphAdapter.create_callbacks()`` — returns a handler list for
   manual injection via ``config={"callbacks": ...}``.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resolve base class: use BaseCallbackHandler when langchain_core is
# available, otherwise fall back to plain ``object``.
# ---------------------------------------------------------------------------

try:
    from langchain_core.callbacks import BaseCallbackHandler as _Base  # type: ignore[import-untyped]
except ImportError:
    _Base = object  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# LangChain callback handler
# ---------------------------------------------------------------------------


class PixelPulseCallbackHandler(_Base):  # type: ignore[misc]
    """LangChain-compatible callback handler that emits PixelPulse events.

    When ``langchain_core`` is installed this class inherits from
    ``BaseCallbackHandler`` so it integrates seamlessly with the LangChain
    callback machinery.  When the package is absent it falls back to plain
    ``object`` and remains duck-type compatible.
    """

    def __init__(self, pp: PixelPulse, *, node_to_agent: dict[str, str] | None = None) -> None:
        # Call the parent __init__ — required when inheriting from
        # BaseCallbackHandler (which itself inherits several mixins).
        if _Base is not object:
            super().__init__()

        self._pp = pp
        # Map LangGraph node names to PixelPulse agent IDs.
        # If not provided we fall back to sanitised node / chain names.
        self._node_to_agent: dict[str, str] = dict(node_to_agent or {})

        # Tracking state ---------------------------------------------------
        # run_id -> (agent_id, start_time)  for chains / nodes
        self._active_chains: dict[str, tuple[str, float]] = {}
        # run_id -> (agent_id, start_time)  for LLM calls
        self._active_llms: dict[str, tuple[str, float]] = {}
        # run_id -> agent_id  for tool calls
        self._active_tools: dict[str, str] = {}
        # parent_run_id -> agent_id (so child callbacks know which agent)
        self._run_agent: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_id_str(run_id: Any) -> str:
        """Normalise a run_id (UUID or str) to a plain string."""
        return str(run_id) if run_id else str(uuid.uuid4())

    def _resolve_agent(
        self,
        name: str | None,
        parent_run_id: Any = None,
    ) -> str:
        """Return the PixelPulse agent_id for a chain / node name."""
        if name and name in self._node_to_agent:
            return self._node_to_agent[name]
        # Try parent chain's agent mapping
        if parent_run_id:
            parent_key = self._run_id_str(parent_run_id)
            if parent_key in self._run_agent:
                return self._run_agent[parent_key]
        # Fallback: sanitise the chain / node name
        if name:
            return name.lower().replace(" ", "-").replace("_", "-")
        return "unknown-agent"

    # ------------------------------------------------------------------
    # Chain / Node callbacks
    # ------------------------------------------------------------------

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any] | Any,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Fired when a chain (or LangGraph node) starts."""
        rid = self._run_id_str(run_id)
        name = (
            (serialized or {}).get("name")
            or (serialized or {}).get("id", [""])[-1]
            if isinstance((serialized or {}).get("id"), list)
            else (serialized or {}).get("name", "")
        )
        # LangGraph passes the node name in metadata or tags
        if metadata and "langgraph_node" in metadata:
            name = metadata["langgraph_node"]
        elif tags:
            # LangGraph often tags with "graph:node:<name>"
            for tag in tags:
                if tag.startswith("graph:node:"):
                    name = tag.split("graph:node:", 1)[1]
                    break

        agent_id = self._resolve_agent(name, parent_run_id)
        self._active_chains[rid] = (agent_id, time.monotonic())
        self._run_agent[rid] = agent_id

        task_summary = ""
        if isinstance(inputs, dict):
            # Try to build a short summary of what was sent
            for key in ("input", "question", "query", "messages"):
                if key in inputs:
                    val = inputs[key]
                    task_summary = str(val)[:200]
                    break

        self._pp.agent_started(agent_id, task=task_summary or f"Running node: {name}")

    def on_chain_end(
        self,
        outputs: dict[str, Any] | Any,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when a chain (or LangGraph node) completes."""
        rid = self._run_id_str(run_id)
        entry = self._active_chains.pop(rid, None)
        if entry is None:
            return
        agent_id, _start = entry

        output_text = ""
        if isinstance(outputs, dict):
            for key in ("output", "text", "result", "answer", "messages"):
                if key in outputs:
                    output_text = str(outputs[key])[:500]
                    break
        if not output_text and outputs is not None:
            output_text = str(outputs)[:500]

        self._pp.agent_completed(agent_id, output=output_text)
        self._run_agent.pop(rid, None)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when a chain (or LangGraph node) errors."""
        rid = self._run_id_str(run_id)
        entry = self._active_chains.pop(rid, None)
        agent_id = entry[0] if entry else self._resolve_agent(None, parent_run_id)
        self._pp.agent_error(agent_id, error=str(error))
        self._run_agent.pop(rid, None)

    # ------------------------------------------------------------------
    # LLM callbacks
    # ------------------------------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when an LLM call begins."""
        rid = self._run_id_str(run_id)
        agent_id = self._resolve_agent(None, parent_run_id)
        self._active_llms[rid] = (agent_id, time.monotonic())
        # Emit a thinking event so the dashboard shows the agent is reasoning
        model_name = (serialized or {}).get("name", "llm")
        first_prompt = (prompts[0][:150] + "...") if prompts else ""
        self._pp.agent_thinking(agent_id, thought=f"Calling {model_name}: {first_prompt}")

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when a chat model call begins (alternative to on_llm_start)."""
        rid = self._run_id_str(run_id)
        agent_id = self._resolve_agent(None, parent_run_id)
        self._active_llms[rid] = (agent_id, time.monotonic())
        model_name = (serialized or {}).get("name", "chat-model")
        self._pp.agent_thinking(agent_id, thought=f"Calling {model_name}")

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when an LLM call completes — extract token usage."""
        rid = self._run_id_str(run_id)
        entry = self._active_llms.pop(rid, None)
        if entry is None:
            return
        agent_id, _start = entry

        # Extract token usage from the LLMResult
        tokens_in = 0
        tokens_out = 0
        model = ""
        if response is not None and hasattr(response, "llm_output") and response.llm_output:
            llm_output = response.llm_output
            usage = llm_output.get("token_usage") or llm_output.get("usage", {})
            if isinstance(usage, dict):
                tokens_in = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                tokens_out = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
            model = llm_output.get("model_name", "") or llm_output.get("model", "")

        if tokens_in or tokens_out:
            self._pp.cost_update(
                agent_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model,
            )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when an LLM call errors."""
        rid = self._run_id_str(run_id)
        entry = self._active_llms.pop(rid, None)
        agent_id = entry[0] if entry else self._resolve_agent(None, parent_run_id)
        self._pp.agent_error(agent_id, error=f"LLM error: {error}")

    # ------------------------------------------------------------------
    # Tool callbacks
    # ------------------------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when a tool is invoked."""
        rid = self._run_id_str(run_id)
        agent_id = self._resolve_agent(None, parent_run_id)
        self._active_tools[rid] = agent_id
        tool_name = (serialized or {}).get("name", "tool")
        self._pp.agent_thinking(agent_id, thought=f"Using tool: {tool_name}")

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when a tool call completes."""
        rid = self._run_id_str(run_id)
        agent_id = self._active_tools.pop(rid, None)
        if agent_id:
            self._pp.artifact_created(
                agent_id,
                artifact_type="tool_output",
                content=str(output)[:500],
            )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when a tool call errors."""
        rid = self._run_id_str(run_id)
        agent_id = self._active_tools.pop(rid, self._resolve_agent(None, parent_run_id))
        self._pp.agent_error(agent_id, error=f"Tool error: {error}")

    # ------------------------------------------------------------------
    # Agent action callbacks (used by legacy LangChain agents)
    # ------------------------------------------------------------------

    def on_agent_action(
        self,
        action: Any,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when a LangChain agent takes an action."""
        agent_id = self._resolve_agent(None, parent_run_id)
        tool_name = getattr(action, "tool", "action")
        tool_input = str(getattr(action, "tool_input", ""))[:200]
        self._pp.agent_thinking(agent_id, thought=f"Action: {tool_name}({tool_input})")

    def on_agent_finish(
        self,
        finish: Any,
        *,
        run_id: Any = None,
        parent_run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Fired when a LangChain agent finishes."""
        agent_id = self._resolve_agent(None, parent_run_id)
        output_text = str(getattr(finish, "return_values", finish))[:500]
        self._pp.agent_completed(agent_id, output=output_text)

    # ------------------------------------------------------------------
    # Retriever callbacks (optional — emit as artifacts)
    # ------------------------------------------------------------------

    def on_retriever_start(
        self, serialized: dict[str, Any], query: str, *, run_id: Any = None,
        parent_run_id: Any = None, **kwargs: Any,
    ) -> None:
        agent_id = self._resolve_agent(None, parent_run_id)
        self._pp.agent_thinking(agent_id, thought=f"Retrieving: {query[:200]}")

    def on_retriever_end(
        self, documents: list[Any], *, run_id: Any = None,
        parent_run_id: Any = None, **kwargs: Any,
    ) -> None:
        agent_id = self._resolve_agent(None, parent_run_id)
        self._pp.artifact_created(
            agent_id,
            artifact_type="retrieval",
            content=f"Retrieved {len(documents)} documents",
        )

    def on_retriever_error(
        self, error: BaseException, *, run_id: Any = None,
        parent_run_id: Any = None, **kwargs: Any,
    ) -> None:
        agent_id = self._resolve_agent(None, parent_run_id)
        self._pp.agent_error(agent_id, error=f"Retriever error: {error}")


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class LangGraphAdapter:
    """Adapter for LangGraph / LangChain agent framework.

    Usage::

        from langgraph.graph import StateGraph
        from pixelpulse import PixelPulse

        pp = PixelPulse(agents={...})
        adapter = pp.adapter("langgraph")

        # Option A — auto-instrument (patches invoke / ainvoke)
        compiled = graph.compile()
        adapter.instrument(compiled)
        compiled.invoke(inputs)

        # Option B — manual callback injection
        compiled.invoke(inputs, config={"callbacks": adapter.create_callbacks()})
    """

    def __init__(self, pp: PixelPulse) -> None:
        self._pp = pp
        self._graph: Any = None
        self._handler: PixelPulseCallbackHandler | None = None
        self._original_invoke: Any = None
        self._original_ainvoke: Any = None
        self._node_to_agent: dict[str, str] = {}

    def set_node_mapping(self, mapping: dict[str, str]) -> LangGraphAdapter:
        """Set a mapping from LangGraph node names to PixelPulse agent IDs.

        Example::

            adapter.set_node_mapping({
                "research_node": "researcher",
                "write_node": "writer",
                "review_node": "reviewer",
            })

        Returns ``self`` for chaining.
        """
        self._node_to_agent = dict(mapping)
        return self

    def instrument(self, graph: Any) -> None:
        """Attach to a LangGraph StateGraph or compiled graph.

        If *graph* is a ``StateGraph`` (not yet compiled), we store it and
        create callbacks but do not patch — the user must still compile.
        If *graph* is a compiled ``CompiledStateGraph`` (has ``invoke``),
        we monkey-patch ``invoke`` and ``ainvoke`` to inject callbacks.
        """
        self._graph = graph
        self._handler = PixelPulseCallbackHandler(self._pp, node_to_agent=self._node_to_agent)

        # Attempt to auto-detect node names from the graph
        self._auto_detect_nodes(graph)

        # Patch invoke / ainvoke on compiled graphs
        if hasattr(graph, "invoke"):
            self._original_invoke = graph.invoke
            graph.invoke = self._patched_invoke

        if hasattr(graph, "ainvoke"):
            self._original_ainvoke = graph.ainvoke
            graph.ainvoke = self._patched_ainvoke

        node_count = len(self._node_to_agent) or "unknown"
        logger.info(
            "LangGraph adapter instrumented (callback-based, %s nodes mapped)",
            node_count,
        )

    def detach(self) -> None:
        """Remove instrumentation — restore original invoke methods."""
        if self._graph is not None:
            if self._original_invoke is not None and hasattr(self._graph, "invoke"):
                self._graph.invoke = self._original_invoke
            if self._original_ainvoke is not None and hasattr(self._graph, "ainvoke"):
                self._graph.ainvoke = self._original_ainvoke
        self._graph = None
        self._handler = None
        self._original_invoke = None
        self._original_ainvoke = None
        self._node_to_agent.clear()

    def create_callbacks(self) -> list:
        """Return a list of LangChain-compatible callback handlers.

        Use this for manual callback injection::

            graph.invoke(inputs, config={"callbacks": adapter.create_callbacks()})
        """
        if self._handler is None:
            self._handler = PixelPulseCallbackHandler(
                self._pp, node_to_agent=self._node_to_agent
            )
        return [self._handler]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auto_detect_nodes(self, graph: Any) -> None:
        """Try to discover node names from the graph object."""
        # CompiledStateGraph stores nodes in graph.nodes
        nodes: dict[str, Any] | None = getattr(graph, "nodes", None)
        if isinstance(nodes, dict):
            for node_name in nodes:
                if node_name not in ("__start__", "__end__"):
                    if node_name not in self._node_to_agent:
                        # Use sanitised node name as agent id
                        self._node_to_agent[node_name] = (
                            node_name.lower().replace(" ", "-").replace("_", "-")
                        )

        # StateGraph (uncompiled) stores nodes in graph._nodes or graph.nodes
        raw_nodes = getattr(graph, "_nodes", None)
        if isinstance(raw_nodes, dict):
            for node_name in raw_nodes:
                if node_name not in self._node_to_agent:
                    self._node_to_agent[node_name] = (
                        node_name.lower().replace(" ", "-").replace("_", "-")
                    )

    def _inject_callbacks(self, config: dict[str, Any] | None) -> dict[str, Any]:
        """Merge our callback handler into the config dict."""
        config = dict(config) if config else {}
        existing = list(config.get("callbacks") or [])
        if self._handler not in existing:
            existing.append(self._handler)
        config["callbacks"] = existing
        return config

    def _patched_invoke(self, inputs: Any, config: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        """Wraps the compiled graph's ``invoke`` to inject callbacks."""
        config = self._inject_callbacks(config)
        run_id = str(uuid.uuid4())
        self._pp.run_started(run_id, name="langgraph-run")
        try:
            result = self._original_invoke(inputs, config=config, **kwargs)
            self._pp.run_completed(run_id, status="completed")
            return result
        except Exception as exc:
            self._pp.run_completed(run_id, status="failed")
            raise

    async def _patched_ainvoke(self, inputs: Any, config: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        """Wraps the compiled graph's ``ainvoke`` to inject callbacks."""
        config = self._inject_callbacks(config)
        run_id = str(uuid.uuid4())
        self._pp.run_started(run_id, name="langgraph-run")
        try:
            result = await self._original_ainvoke(inputs, config=config, **kwargs)
            self._pp.run_completed(run_id, status="completed")
            return result
        except Exception as exc:
            self._pp.run_completed(run_id, status="failed")
            raise
