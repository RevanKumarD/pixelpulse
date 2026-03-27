"""Persistent storage for PixelPulse run history.

Provides SQLite-backed repositories for persisting runs and events,
plus a bus subscriber that auto-saves events as they flow through.
"""
from __future__ import annotations

from pixelpulse.storage.db import Database
from pixelpulse.storage.event_repo import EventRepository
from pixelpulse.storage.models import EventRecord, RunRecord, RunStatus
from pixelpulse.storage.run_repo import RunRepository
from pixelpulse.storage.subscriber import StorageSubscriber

__all__ = [
    "Database",
    "EventRecord",
    "EventRepository",
    "RunRecord",
    "RunRepository",
    "RunStatus",
    "StorageSubscriber",
]
