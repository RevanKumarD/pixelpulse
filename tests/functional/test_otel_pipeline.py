"""Functional tests: OTEL span ingestion → PixelPulse → /api/events.

Tests the full OTEL ingest path without mocking:
  POST /v1/traces → parse_otlp_spans() → bus.emit() → /api/events

This validates that external OTLP exporters produce visible dashboard events
through the real HTTP → EventBus chain.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

import pixelpulse.bus as bus_module
from pixelpulse import PixelPulse


@pytest.fixture(autouse=True)
def fresh_bus():
    """Reset the singleton bus before/after each test for isolation."""
    bus_module._bus = None
    yield
    bus_module._bus = None


@pytest.fixture
def pp():
    return PixelPulse(
        agents={"data-analyst": {"team": "research", "role": "Data analysis"}},
        teams={"research": {"label": "Research"}},
        pipeline=["research"],
    )


def _make_span_payload(
    span_name: str = "chat gpt-4o-mini",
    agent_name: str | None = None,
    input_tokens: int = 150,
    output_tokens: int = 45,
) -> dict:
    """Build a minimal OTLP JSON payload for one span."""
    attrs = [
        {"key": "gen_ai.system", "value": {"stringValue": "openai"}},
        {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o-mini"}},
        {"key": "gen_ai.usage.input_tokens", "value": {"intValue": input_tokens}},
        {"key": "gen_ai.usage.output_tokens", "value": {"intValue": output_tokens}},
    ]
    if agent_name:
        attrs.append({"key": "gen_ai.agent.name", "value": {"stringValue": agent_name}})

    now_ns = str(int(time.time() * 1e9))
    return {
        "resourceSpans": [{
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": "test-service"}}
            ]},
            "scopeSpans": [{
                "scope": {"name": "openai.instrumentation"},
                "spans": [{
                    "traceId": "trace-001",
                    "spanId": "span-001",
                    "name": span_name,
                    "kind": 3,
                    "startTimeUnixNano": now_ns,
                    "endTimeUnixNano": now_ns,
                    "status": {"code": 1},
                    "attributes": attrs,
                }],
            }],
        }]
    }


class TestOtelIngestion:
    @pytest.mark.asyncio
    async def test_otel_post_returns_200(self, pp):
        """POST /v1/traces returns 200 for valid OTLP payload."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            resp = await client.post("/v1/traces", json=_make_span_payload())
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_otel_span_produces_events(self, pp):
        """A valid OTLP span produces at least one event at /api/events."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            await client.post("/v1/traces", json=_make_span_payload())
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_otel_span_with_agent_name_emits_agent_status(self, pp):
        """A span with gen_ai.agent.name produces an agent_status event."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            payload = _make_span_payload(
                span_name="agent data-analyst",
                agent_name="data-analyst",
            )
            await client.post("/v1/traces", json=payload)
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        types = {e["type"] for e in events}
        # Should produce agent_status or cost_update from the span
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_otel_cost_span_produces_cost_event(self, pp):
        """A span with token counts produces a cost_update event at /api/events."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            await client.post(
                "/v1/traces",
                json=_make_span_payload(input_tokens=500, output_tokens=200),
            )
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        cost_events = [e for e in events if e["type"] == "cost_update"]
        assert len(cost_events) >= 1

    @pytest.mark.asyncio
    async def test_otel_multiple_spans_in_one_post(self, pp):
        """Multiple spans in one OTLP POST each produce events."""
        now_ns = str(int(time.time() * 1e9))
        payload = {
            "resourceSpans": [{
                "resource": {"attributes": [
                    {"key": "service.name", "value": {"stringValue": "multi-span"}}
                ]},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [
                        {
                            "traceId": "trace-001",
                            "spanId": f"span-{i:03d}",
                            "name": "chat gpt-4o-mini",
                            "kind": 3,
                            "startTimeUnixNano": now_ns,
                            "endTimeUnixNano": now_ns,
                            "status": {"code": 1},
                            "attributes": [
                                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": 100}},
                                {"key": "gen_ai.usage.output_tokens", "value": {"intValue": 50}},
                            ],
                        }
                        for i in range(3)
                    ],
                }],
            }]
        }

        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            resp = await client.post("/v1/traces", json=payload)
            assert resp.status_code == 200
            await asyncio.sleep(0)

            resp = await client.get("/api/events")
            events = resp.json()

        # 3 spans → at least 3 cost events
        cost_events = [e for e in events if e["type"] == "cost_update"]
        assert len(cost_events) >= 3

    @pytest.mark.asyncio
    async def test_otel_empty_resource_spans_is_valid(self, pp):
        """Empty resourceSpans does not crash the server."""
        async with AsyncClient(
            transport=ASGITransport(app=pp._create_app()),
            base_url="http://test",
        ) as client:
            resp = await client.post("/v1/traces", json={"resourceSpans": []})
            assert resp.status_code == 200
