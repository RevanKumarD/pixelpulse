"""Tests for the PixelPulse event bus."""

import pytest

from pixelpulse.bus import EventBus


@pytest.fixture
def bus():
    return EventBus()


class TestEventBus:
    async def test_subscribe_and_emit(self, bus):
        received = []

        async def callback(event):
            received.append(event)

        await bus.subscribe(callback)
        await bus.emit({"type": "test", "payload": {"data": 1}})

        assert len(received) == 1
        assert received[0]["type"] == "test"

    async def test_multiple_subscribers(self, bus):
        received_a = []
        received_b = []

        async def cb_a(event):
            received_a.append(event)

        async def cb_b(event):
            received_b.append(event)

        await bus.subscribe(cb_a)
        await bus.subscribe(cb_b)
        await bus.emit({"type": "test"})

        assert len(received_a) == 1
        assert len(received_b) == 1

    async def test_unsubscribe(self, bus):
        received = []

        async def callback(event):
            received.append(event)

        await bus.subscribe(callback)
        await bus.emit({"type": "first"})
        await bus.unsubscribe(callback)
        await bus.emit({"type": "second"})

        assert len(received) == 1
        assert received[0]["type"] == "first"

    async def test_auto_adds_timestamp(self, bus):
        received = []

        async def callback(event):
            received.append(event)

        await bus.subscribe(callback)
        await bus.emit({"type": "test"})

        assert "timestamp" in received[0]

    async def test_subscriber_error_does_not_block_others(self, bus):
        received = []

        async def bad_callback(event):
            raise RuntimeError("boom")

        async def good_callback(event):
            received.append(event)

        await bus.subscribe(bad_callback)
        await bus.subscribe(good_callback)
        await bus.emit({"type": "test"})

        assert len(received) == 1

    async def test_history(self, bus):
        for i in range(5):
            await bus.emit({"type": f"test_{i}"})

        history = bus.get_history()
        assert len(history) == 5
        assert history[0]["type"] == "test_0"
        assert history[4]["type"] == "test_4"

    async def test_duplicate_subscribe_ignored(self, bus):
        received = []

        async def callback(event):
            received.append(event)

        await bus.subscribe(callback)
        await bus.subscribe(callback)  # duplicate
        await bus.emit({"type": "test"})

        assert len(received) == 1  # Not 2
