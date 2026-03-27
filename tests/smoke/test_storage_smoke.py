"""Smoke tests for storage module initialization and basic wiring."""
from __future__ import annotations

import pytest
import pytest_asyncio

from pixelpulse.storage.db import Database
from pixelpulse.storage.event_repo import EventRepository
from pixelpulse.storage.models import EventRecord, RunRecord, RunStatus
from pixelpulse.storage.run_repo import RunRepository
from pixelpulse.storage.subscriber import StorageSubscriber


class TestStorageModuleImports:
    """Verify all storage modules import cleanly."""

    def test_import_db(self):
        from pixelpulse.storage.db import Database
        assert Database is not None

    def test_import_models(self):
        from pixelpulse.storage.models import EventRecord, RunRecord, RunStatus
        assert RunStatus.ACTIVE == "active"
        assert RunStatus.COMPLETED == "completed"

    def test_import_run_repo(self):
        from pixelpulse.storage.run_repo import RunRepository
        assert RunRepository is not None

    def test_import_event_repo(self):
        from pixelpulse.storage.event_repo import EventRepository
        assert EventRepository is not None

    def test_import_subscriber(self):
        from pixelpulse.storage.subscriber import StorageSubscriber
        assert StorageSubscriber is not None

    def test_package_exports(self):
        """Verify __init__.py exports all public symbols."""
        from pixelpulse.storage import (
            Database,
            EventRecord,
            EventRepository,
            RunRecord,
            RunRepository,
            RunStatus,
            StorageSubscriber,
        )
        assert all([Database, EventRecord, EventRepository, RunRecord,
                     RunRepository, RunStatus, StorageSubscriber])


class TestDatabaseSmoke:
    """Basic database lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_and_close(self, tmp_path):
        db = Database(tmp_path / "smoke.db")
        await db.connect()
        assert db._conn is not None
        await db.close()

    @pytest.mark.asyncio
    async def test_context_manager(self, tmp_path):
        db = Database(tmp_path / "smoke.db")
        await db.connect()
        async with db:
            pass  # Should not raise

    @pytest.mark.asyncio
    async def test_schema_created(self, tmp_path):
        db = Database(tmp_path / "smoke.db")
        await db.connect()
        # Verify tables exist
        async with db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            tables = {row[0] for row in await cursor.fetchall()}
        assert "runs" in tables
        assert "events" in tables
        assert "schema_version" in tables
        await db.close()

    @pytest.mark.asyncio
    async def test_wal_mode(self, tmp_path):
        db = Database(tmp_path / "smoke.db")
        await db.connect()
        async with db._conn.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
        assert row[0] == "wal"
        await db.close()


class TestRecordDefaults:
    """Verify dataclass defaults are sensible."""

    def test_run_record_defaults(self):
        run = RunRecord(id="r1", name="Test", status="active", started_at="now")
        assert run.completed_at == ""
        assert run.total_cost == 0.0
        assert run.total_tokens_in == 0
        assert run.total_tokens_out == 0
        assert run.agent_count == 0
        assert run.event_count == 0
        assert run.metadata == {}

    def test_event_record_defaults(self):
        evt = EventRecord(id="e1", run_id="r1", type="test", timestamp="now")
        assert evt.source_framework == ""
        assert evt.payload == {}
        assert evt.agent_id == ""


class TestSubscriberSmoke:
    """Verify StorageSubscriber initializes without errors."""

    @pytest.mark.asyncio
    async def test_subscriber_creates_without_db(self):
        """StorageSubscriber should init with a Database instance."""
        # Can't attach without a real DB, but constructor should work
        db = Database(":memory:")  # Won't connect, just init
        sub = StorageSubscriber(db)
        assert sub.current_run_id is None
