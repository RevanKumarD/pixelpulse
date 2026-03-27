"""Tests for the OTel SpanProcessor and OTLP JSON ingestion."""
from __future__ import annotations

import pytest

from pixelpulse.otel import (
    _OtlpSpanProxy,
    parse_otlp_spans,
    span_to_events,
)
from pixelpulse.protocol import (
    AGENT_COMPLETED,
    AGENT_ERROR,
    AGENT_STARTED,
    AGENT_THINKING,
    COST_UPDATE,
)


# ---- Helpers to build fake spans ----


class FakeStatus:
    def __init__(self, code: int = 0, description: str = ""):
        self.status_code = code
        self.description = description


class FakeEvent:
    def __init__(self, name: str = "", attributes: dict | None = None):
        self.name = name
        self.attributes = attributes or {}


class FakeSpan:
    """Minimal span-like object for testing span_to_events."""

    def __init__(
        self,
        name: str = "",
        attributes: dict | None = None,
        status: FakeStatus | None = None,
        events: list[FakeEvent] | None = None,
    ):
        self.name = name
        self.attributes = attributes or {}
        self.status = status or FakeStatus()
        self.events = events or []


# ---- Tests ----


class TestSpanToEvents:
    """Test the span_to_events conversion logic."""

    def test_agent_span_produces_started_and_completed(self):
        span = FakeSpan(
            name="gen_ai.agent.research",
            attributes={
                "gen_ai.agent.name": "researcher",
                "gen_ai.request.model": "gpt-4o",
            },
        )
        events = span_to_events(span)

        types = [e["type"] for e in events]
        assert AGENT_STARTED in types
        assert AGENT_COMPLETED in types
        assert events[0]["payload"]["agent_id"] == "researcher"
        assert events[0]["payload"]["model"] == "gpt-4o"

    def test_agent_span_with_tokens_emits_cost_update(self):
        span = FakeSpan(
            name="gen_ai.agent.write",
            attributes={
                "gen_ai.agent.name": "writer",
                "gen_ai.request.model": "claude-sonnet-4-20250514",
                "gen_ai.usage.input_tokens": 500,
                "gen_ai.usage.output_tokens": 1200,
            },
        )
        events = span_to_events(span)

        types = [e["type"] for e in events]
        assert COST_UPDATE in types

        cost_event = next(e for e in events if e["type"] == COST_UPDATE)
        assert cost_event["payload"]["tokens_in"] == 500
        assert cost_event["payload"]["tokens_out"] == 1200
        assert cost_event["payload"]["model"] == "claude-sonnet-4-20250514"

    def test_error_span_emits_agent_error(self):
        span = FakeSpan(
            name="gen_ai.agent.review",
            attributes={"gen_ai.agent.name": "reviewer"},
            status=FakeStatus(code=2, description="Rate limit exceeded"),
        )
        events = span_to_events(span)

        assert len(events) == 1
        assert events[0]["type"] == AGENT_ERROR
        assert events[0]["payload"]["error"] == "Rate limit exceeded"
        assert events[0]["payload"]["agent_id"] == "reviewer"

    def test_error_from_exception_event(self):
        span = FakeSpan(
            name="gen_ai.agent.broken",
            attributes={"gen_ai.agent.name": "broken_agent"},
            status=FakeStatus(code=2),
            events=[
                FakeEvent(
                    name="exception",
                    attributes={"exception.message": "Connection refused"},
                )
            ],
        )
        events = span_to_events(span)

        assert events[0]["type"] == AGENT_ERROR
        assert events[0]["payload"]["error"] == "Connection refused"

    def test_tool_span_emits_thinking(self):
        span = FakeSpan(
            name="gen_ai.tool.web_search",
            attributes={
                "gen_ai.tool.name": "web_search",
                "gen_ai.tool.description": "Searches the web",
            },
        )
        events = span_to_events(span)

        assert len(events) == 1
        assert events[0]["type"] == AGENT_THINKING
        assert "web_search" in events[0]["payload"]["thought"]
        assert "Searches the web" in events[0]["payload"]["thought"]

    def test_tool_span_without_description(self):
        span = FakeSpan(
            name="gen_ai.tool.calculator",
            attributes={"gen_ai.tool.name": "calculator"},
        )
        events = span_to_events(span)

        assert events[0]["type"] == AGENT_THINKING
        assert events[0]["payload"]["thought"] == "Using tool: calculator"

    def test_span_without_agent_name_uses_span_name(self):
        span = FakeSpan(name="gen_ai.agent.my_agent", attributes={})
        events = span_to_events(span)

        # Should extract "my_agent" from the span name
        assert events[0]["payload"]["agent_id"] == "my_agent"

    def test_no_tokens_means_no_cost_event(self):
        span = FakeSpan(
            name="gen_ai.agent.cheap",
            attributes={"gen_ai.agent.name": "cheap_agent"},
        )
        events = span_to_events(span)

        types = [e["type"] for e in events]
        assert COST_UPDATE not in types

    def test_source_framework_is_otel(self):
        span = FakeSpan(
            name="gen_ai.agent.test",
            attributes={"gen_ai.agent.name": "tester"},
        )
        events = span_to_events(span)

        for event in events:
            assert event["source"]["framework"] == "otel"


class TestOtlpJsonParsing:
    """Test the OTLP JSON parsing and proxy objects."""

    def test_parse_minimal_otlp_json(self):
        otlp = {
            "resourceSpans": [{
                "scopeSpans": [{
                    "spans": [
                        {"name": "gen_ai.agent.test", "attributes": [], "events": []},
                    ]
                }]
            }]
        }
        proxies = parse_otlp_spans(otlp)
        assert len(proxies) == 1
        assert proxies[0].name == "gen_ai.agent.test"

    def test_parse_attributes_string_value(self):
        otlp = {
            "resourceSpans": [{
                "scopeSpans": [{
                    "spans": [{
                        "name": "gen_ai.agent.test",
                        "attributes": [
                            {"key": "gen_ai.agent.name", "value": {"stringValue": "researcher"}},
                        ],
                        "events": [],
                    }]
                }]
            }]
        }
        proxies = parse_otlp_spans(otlp)
        assert proxies[0].attributes["gen_ai.agent.name"] == "researcher"

    def test_parse_attributes_int_value(self):
        otlp = {
            "resourceSpans": [{
                "scopeSpans": [{
                    "spans": [{
                        "name": "gen_ai.agent.test",
                        "attributes": [
                            {"key": "gen_ai.usage.input_tokens", "value": {"intValue": 500}},
                            {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "1200"}},
                        ],
                        "events": [],
                    }]
                }]
            }]
        }
        proxies = parse_otlp_spans(otlp)
        assert proxies[0].attributes["gen_ai.usage.input_tokens"] == 500
        assert proxies[0].attributes["gen_ai.usage.output_tokens"] == 1200

    def test_parse_status_error(self):
        otlp = {
            "resourceSpans": [{
                "scopeSpans": [{
                    "spans": [{
                        "name": "gen_ai.agent.broken",
                        "attributes": [
                            {"key": "gen_ai.agent.name", "value": {"stringValue": "broken"}},
                        ],
                        "status": {"code": 2, "message": "Something went wrong"},
                        "events": [],
                    }]
                }]
            }]
        }
        proxies = parse_otlp_spans(otlp)
        events = span_to_events(proxies[0])

        assert events[0]["type"] == AGENT_ERROR
        assert events[0]["payload"]["error"] == "Something went wrong"

    def test_parse_empty_otlp(self):
        assert parse_otlp_spans({}) == []
        assert parse_otlp_spans({"resourceSpans": []}) == []

    def test_multiple_spans_in_one_scope(self):
        otlp = {
            "resourceSpans": [{
                "scopeSpans": [{
                    "spans": [
                        {"name": "gen_ai.agent.a", "attributes": [], "events": []},
                        {"name": "gen_ai.agent.b", "attributes": [], "events": []},
                        {"name": "gen_ai.tool.c", "attributes": [], "events": []},
                    ]
                }]
            }]
        }
        proxies = parse_otlp_spans(otlp)
        assert len(proxies) == 3

    def test_end_to_end_otlp_to_events(self):
        """Full round-trip: OTLP JSON → proxy → PixelPulse events."""
        otlp = {
            "resourceSpans": [{
                "scopeSpans": [{
                    "spans": [{
                        "name": "gen_ai.agent.researcher",
                        "attributes": [
                            {"key": "gen_ai.agent.name", "value": {"stringValue": "researcher"}},
                            {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}},
                            {"key": "gen_ai.usage.input_tokens", "value": {"intValue": 100}},
                            {"key": "gen_ai.usage.output_tokens", "value": {"intValue": 500}},
                        ],
                        "events": [],
                    }]
                }]
            }]
        }
        proxies = parse_otlp_spans(otlp)
        events = span_to_events(proxies[0])

        types = [e["type"] for e in events]
        assert AGENT_STARTED in types
        assert COST_UPDATE in types
        assert AGENT_COMPLETED in types

        cost = next(e for e in events if e["type"] == COST_UPDATE)
        assert cost["payload"]["tokens_in"] == 100
        assert cost["payload"]["model"] == "gpt-4o"
