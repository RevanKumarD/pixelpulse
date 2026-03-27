"""OpenTelemetry SpanProcessor that converts OTel GenAI spans to PixelPulse events.

All OpenTelemetry imports are guarded — PixelPulse works without opentelemetry installed.
Install the ``otel`` extra to enable: ``pip install pixelpulse[otel]``

Usage::

    from opentelemetry.sdk.trace import TracerProvider
    from pixelpulse import PixelPulse
    from pixelpulse.otel import PixelPulseSpanProcessor

    pp = PixelPulse(agents={...}, teams={...})
    provider = TracerProvider()
    provider.add_span_processor(PixelPulseSpanProcessor(pp))
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pixelpulse.protocol import (
    AGENT_COMPLETED,
    AGENT_ERROR,
    AGENT_STARTED,
    AGENT_THINKING,
    COST_UPDATE,
    create_event,
)

if TYPE_CHECKING:
    from pixelpulse.core import PixelPulse

logger = logging.getLogger(__name__)

# ---- OTel GenAI Semantic Convention constants ----
# These follow the OpenTelemetry GenAI semantic conventions:
# https://opentelemetry.io/docs/specs/semconv/gen-ai/

_GENAI_AGENT = "gen_ai.agent"
_GENAI_CHAT = "gen_ai.chat"
_GENAI_TOOL = "gen_ai.tool"

_ATTR_AGENT_NAME = "gen_ai.agent.name"
_ATTR_AGENT_ID = "gen_ai.agent.id"
_ATTR_REQUEST_MODEL = "gen_ai.request.model"
_ATTR_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
_ATTR_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
_ATTR_TOOL_NAME = "gen_ai.tool.name"
_ATTR_TOOL_DESCRIPTION = "gen_ai.tool.description"
_ATTR_RESPONSE_FINISH_REASON = "gen_ai.response.finish_reasons"

# Status codes from OTel spec
_STATUS_ERROR = 2  # StatusCode.ERROR


try:
    from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
    from opentelemetry.trace import StatusCode

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

    # Provide a base class so the processor can still be defined (it will
    # raise at instantiation if OTel is missing).
    class SpanProcessor:  # type: ignore[no-redef]
        """Placeholder when opentelemetry-sdk is not installed."""

        def on_start(self, span: Any, parent_context: Any = None) -> None:
            pass

        def on_end(self, span: Any) -> None:
            pass

        def shutdown(self) -> None:
            pass

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    class ReadableSpan:  # type: ignore[no-redef]
        """Placeholder type."""

    class StatusCode:  # type: ignore[no-redef]
        ERROR = 2
        OK = 1
        UNSET = 0


def _get_attr(span: Any, key: str, default: Any = None) -> Any:
    """Safely extract an attribute from a span."""
    attrs = getattr(span, "attributes", None) or {}
    return attrs.get(key, default)


def _get_agent_id(span: Any) -> str:
    """Extract agent identifier from span attributes or name."""
    agent_id = _get_attr(span, _ATTR_AGENT_NAME) or _get_attr(span, _ATTR_AGENT_ID)
    if agent_id:
        return str(agent_id)
    # Fall back to span name, stripping common prefixes
    name = getattr(span, "name", "") or ""
    for prefix in ("gen_ai.agent.", "agent.", ""):
        if prefix and name.startswith(prefix):
            return name[len(prefix):]
    return name or "unknown"


def _get_span_kind_str(span: Any) -> str:
    """Get the GenAI span kind from the span name prefix."""
    name = getattr(span, "name", "") or ""
    name_lower = name.lower()
    if "agent" in name_lower or name_lower.startswith(_GENAI_AGENT):
        return "agent"
    if "tool" in name_lower or name_lower.startswith(_GENAI_TOOL):
        return "tool"
    if "chat" in name_lower or name_lower.startswith(_GENAI_CHAT):
        return "chat"
    return "unknown"


def _is_error_span(span: Any) -> bool:
    """Check if a span has error status."""
    status = getattr(span, "status", None)
    if status is None:
        return False
    status_code = getattr(status, "status_code", None)
    if status_code is None:
        return False
    # Compare by int value to support both real StatusCode enums and raw ints
    try:
        code_val = int(status_code.value) if hasattr(status_code, "value") else int(status_code)
    except (TypeError, ValueError):
        return False
    return code_val == _STATUS_ERROR


def _get_error_message(span: Any) -> str:
    """Extract error message from a span."""
    status = getattr(span, "status", None)
    if status is not None:
        desc = getattr(status, "description", None)
        if desc:
            return str(desc)
    # Check events for exception details
    events = getattr(span, "events", None) or ()
    for event in events:
        event_name = getattr(event, "name", "")
        if event_name == "exception":
            event_attrs = getattr(event, "attributes", {}) or {}
            msg = event_attrs.get("exception.message", "")
            if msg:
                return str(msg)
    return "Unknown error"


def span_to_events(span: Any) -> list[dict]:
    """Convert an OTel span to a list of PixelPulse event dicts.

    A single span may produce multiple events (e.g., agent_started +
    cost_update + agent_completed).

    This function is the core conversion logic used by both the
    SpanProcessor (Python SDK path) and the ``/v1/traces`` HTTP endpoint.
    """
    events: list[dict] = []
    span_kind = _get_span_kind_str(span)
    agent_id = _get_agent_id(span)
    model = _get_attr(span, _ATTR_REQUEST_MODEL, "")

    # ---- Tool spans → agent_thinking ----
    if span_kind == "tool":
        tool_name = _get_attr(span, _ATTR_TOOL_NAME) or agent_id
        thought = f"Using tool: {tool_name}"
        desc = _get_attr(span, _ATTR_TOOL_DESCRIPTION)
        if desc:
            thought = f"Using tool: {tool_name} — {desc}"
        events.append(create_event(
            AGENT_THINKING,
            {"agent_id": agent_id, "thought": thought, "tool": str(tool_name)},
            source_framework="otel",
        ))
        return events

    # ---- Agent / Chat spans ----
    if _is_error_span(span):
        error_msg = _get_error_message(span)
        events.append(create_event(
            AGENT_ERROR,
            {"agent_id": agent_id, "error": error_msg, "model": model},
            source_framework="otel",
        ))
        return events

    # Emit agent_started
    task = getattr(span, "name", "") or ""
    events.append(create_event(
        AGENT_STARTED,
        {"agent_id": agent_id, "task": task, "model": model},
        source_framework="otel",
    ))

    # Emit cost_update if token usage is present
    tokens_in = _get_attr(span, _ATTR_USAGE_INPUT_TOKENS, 0)
    tokens_out = _get_attr(span, _ATTR_USAGE_OUTPUT_TOKENS, 0)
    if tokens_in or tokens_out:
        events.append(create_event(
            COST_UPDATE,
            {
                "agent_id": agent_id,
                "tokens_in": int(tokens_in),
                "tokens_out": int(tokens_out),
                "model": model,
                "cost": 0,  # Cost estimation is caller's responsibility
            },
            source_framework="otel",
        ))

    # Emit agent_completed
    events.append(create_event(
        AGENT_COMPLETED,
        {"agent_id": agent_id, "output": "", "model": model},
        source_framework="otel",
    ))

    return events


class PixelPulseSpanProcessor(SpanProcessor):
    """OTel SpanProcessor that forwards GenAI spans to a PixelPulse instance.

    Attach to any ``TracerProvider``::

        provider.add_span_processor(PixelPulseSpanProcessor(pp))

    The processor recognises spans following the OTel GenAI semantic
    conventions and converts them to the appropriate PixelPulse events
    (agent_started, agent_completed, agent_error, agent_thinking, cost_update).
    """

    def __init__(self, pp: PixelPulse) -> None:
        if not _OTEL_AVAILABLE:
            raise ImportError(
                "opentelemetry-sdk is required for PixelPulseSpanProcessor. "
                "Install it with: pip install pixelpulse[otel]"
            )
        self._pp = pp

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        """Called when a span starts. No-op — we process on end."""

    def on_end(self, span: Any) -> None:
        """Called when a span ends. Convert to PixelPulse events and emit."""
        try:
            pp_events = span_to_events(span)
            for event in pp_events:
                self._pp.emit(event)
        except Exception:
            logger.exception("Failed to process OTel span: %s", getattr(span, "name", "?"))

    def shutdown(self) -> None:
        """Graceful shutdown — nothing to clean up."""

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush — events are emitted synchronously, always returns True."""
        return True


def parse_otlp_spans(otlp_json: dict) -> list[Any]:
    """Parse OTLP JSON export format into lightweight span-like objects.

    The OTLP JSON format wraps spans in::

        { "resourceSpans": [{ "scopeSpans": [{ "spans": [...] }] }] }

    Each raw span dict is wrapped in an :class:`_OtlpSpanProxy` so that
    :func:`span_to_events` can read it with the same attribute-access API
    used for real OTel ``ReadableSpan`` objects.
    """
    proxies: list[Any] = []
    for resource_span in otlp_json.get("resourceSpans", []):
        for scope_span in resource_span.get("scopeSpans", []):
            for raw in scope_span.get("spans", []):
                proxies.append(_OtlpSpanProxy(raw))
    return proxies


class _OtlpSpanProxy:
    """Lightweight proxy that gives a raw OTLP JSON span dict the same
    attribute-access interface as an OTel ``ReadableSpan``.
    """

    def __init__(self, raw: dict) -> None:
        self._raw = raw
        self.name: str = raw.get("name", "")
        self.attributes: dict = self._flatten_attrs(raw.get("attributes", []))
        self.events: list[_OtlpEventProxy] = [
            _OtlpEventProxy(e) for e in raw.get("events", [])
        ]
        self.status = _OtlpStatusProxy(raw.get("status", {}))

    @staticmethod
    def _flatten_attrs(attrs_list: list[dict]) -> dict:
        """Convert OTLP attribute array to a flat dict.

        OTLP attributes are ``[{"key": "k", "value": {"stringValue": "v"}}]``.
        """
        result: dict = {}
        for attr in attrs_list:
            key = attr.get("key", "")
            value_obj = attr.get("value", {})
            # Extract the actual value from the typed wrapper
            for vtype in ("stringValue", "intValue", "doubleValue", "boolValue"):
                if vtype in value_obj:
                    val = value_obj[vtype]
                    # intValue and doubleValue may come as strings in JSON
                    if vtype == "intValue":
                        val = int(val)
                    elif vtype == "doubleValue":
                        val = float(val)
                    result[key] = val
                    break
            else:
                # arrayValue or kvlistValue — store raw
                result[key] = value_obj
        return result


class _OtlpEventProxy:
    """Proxy for an OTLP span event."""

    def __init__(self, raw: dict) -> None:
        self.name: str = raw.get("name", "")
        self.attributes: dict = _OtlpSpanProxy._flatten_attrs(raw.get("attributes", []))


class _OtlpStatusProxy:
    """Proxy for an OTLP span status."""

    def __init__(self, raw: dict) -> None:
        self.description: str = raw.get("message", "")
        code = raw.get("code", 0)
        self.status_code = code
