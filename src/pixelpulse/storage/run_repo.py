"""Repository for persistent run records."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pixelpulse.storage.models import RunRecord, RunStatus

if TYPE_CHECKING:
    from pixelpulse.storage.db import Database


class RunRepository:
    """CRUD operations for pipeline runs stored in SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, run: RunRecord) -> RunRecord:
        """Insert a new run record."""
        await self._db.conn.execute(
            """INSERT INTO runs (id, name, status, started_at, completed_at,
               total_cost, total_tokens_in, total_tokens_out,
               agent_count, event_count, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.id,
                run.name,
                run.status,
                run.started_at,
                run.completed_at,
                run.total_cost,
                run.total_tokens_in,
                run.total_tokens_out,
                run.agent_count,
                run.event_count,
                json.dumps(run.metadata),
            ),
        )
        await self._db.conn.commit()
        return run

    async def get(self, run_id: str) -> RunRecord | None:
        """Fetch a run by ID."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        return RunRecord.from_row(row) if row else None

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[RunRecord]:
        """List runs, newest first."""
        if status:
            cursor = await self._db.conn.execute(
                "SELECT * FROM runs WHERE status = ? ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            cursor = await self._db.conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cursor.fetchall()
        return [RunRecord.from_row(r) for r in rows]

    async def count(self, status: str | None = None) -> int:
        """Count total runs, optionally filtered by status."""
        if status:
            cursor = await self._db.conn.execute(
                "SELECT COUNT(*) FROM runs WHERE status = ?", (status,)
            )
        else:
            cursor = await self._db.conn.execute("SELECT COUNT(*) FROM runs")
        row = await cursor.fetchone()
        return row[0]

    async def update_status(
        self,
        run_id: str,
        status: str,
        completed_at: str = "",
        total_cost: float = 0.0,
        total_tokens_in: int = 0,
        total_tokens_out: int = 0,
    ) -> RunRecord | None:
        """Update a run's status and computed totals."""
        await self._db.conn.execute(
            """UPDATE runs SET status = ?, completed_at = ?,
               total_cost = ?, total_tokens_in = ?, total_tokens_out = ?
               WHERE id = ?""",
            (status, completed_at, total_cost, total_tokens_in, total_tokens_out, run_id),
        )
        await self._db.conn.commit()
        return await self.get(run_id)

    async def increment_event_count(self, run_id: str) -> None:
        """Increment the event count for a run."""
        await self._db.conn.execute(
            "UPDATE runs SET event_count = event_count + 1 WHERE id = ?",
            (run_id,),
        )
        await self._db.conn.commit()

    async def update_agent_count(self, run_id: str, count: int) -> None:
        """Set the agent count for a run."""
        await self._db.conn.execute(
            "UPDATE runs SET agent_count = ? WHERE id = ?",
            (count, run_id),
        )
        await self._db.conn.commit()

    async def delete(self, run_id: str) -> bool:
        """Delete a run and all its events (cascade)."""
        cursor = await self._db.conn.execute(
            "DELETE FROM runs WHERE id = ?", (run_id,)
        )
        await self._db.conn.commit()
        return cursor.rowcount > 0

    async def export_run(self, run_id: str) -> dict | None:
        """Export a run with all events as a JSON-serializable dict."""
        run = await self.get(run_id)
        if run is None:
            return None

        cursor = await self._db.conn.execute(
            "SELECT * FROM events WHERE run_id = ? ORDER BY timestamp ASC",
            (run_id,),
        )
        rows = await cursor.fetchall()
        from pixelpulse.storage.models import EventRecord

        events = [EventRecord.from_row(r).to_dict() for r in rows]

        return {
            "version": 1,
            "run": run.to_dict(),
            "events": events,
        }
