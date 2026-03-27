"""Repository for persistent event records."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pixelpulse.storage.models import EventRecord

if TYPE_CHECKING:
    from pixelpulse.storage.db import Database


class EventRepository:
    """CRUD operations for events stored in SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, event: EventRecord) -> EventRecord:
        """Insert a new event record."""
        await self._db.conn.execute(
            """INSERT INTO events (id, run_id, type, timestamp,
               source_framework, payload, agent_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event.id,
                event.run_id,
                event.type,
                event.timestamp,
                event.source_framework,
                json.dumps(event.payload),
                event.agent_id,
            ),
        )
        await self._db.conn.commit()
        return event

    async def get(self, event_id: str) -> EventRecord | None:
        """Fetch an event by ID."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()
        return EventRecord.from_row(row) if row else None

    async def list_by_run(
        self,
        run_id: str,
        event_type: str | None = None,
        agent_id: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[EventRecord]:
        """List events for a run, ordered by timestamp."""
        conditions = ["run_id = ?"]
        params: list = [run_id]

        if event_type:
            conditions.append("type = ?")
            params.append(event_type)
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        where = " AND ".join(conditions)
        params.extend([limit, offset])

        cursor = await self._db.conn.execute(
            f"SELECT * FROM events WHERE {where} ORDER BY timestamp ASC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cursor.fetchall()
        return [EventRecord.from_row(r) for r in rows]

    async def list_by_agent(
        self,
        agent_id: str,
        run_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[EventRecord]:
        """List events for a specific agent, across runs or within a run."""
        conditions = ["agent_id = ?"]
        params: list = [agent_id]

        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        where = " AND ".join(conditions)
        params.extend([limit, offset])

        cursor = await self._db.conn.execute(
            f"SELECT * FROM events WHERE {where} ORDER BY timestamp ASC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cursor.fetchall()
        return [EventRecord.from_row(r) for r in rows]

    async def count_by_run(self, run_id: str) -> int:
        """Count events in a run."""
        cursor = await self._db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        return row[0]

    async def get_agent_ids_for_run(self, run_id: str) -> list[str]:
        """Get distinct agent IDs that participated in a run."""
        cursor = await self._db.conn.execute(
            "SELECT DISTINCT agent_id FROM events WHERE run_id = ? AND agent_id != ''",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

    async def get_cost_summary(self, run_id: str) -> dict:
        """Compute cost summary for a run from cost_update events."""
        cursor = await self._db.conn.execute(
            "SELECT payload FROM events WHERE run_id = ? AND type = 'cost_update'",
            (run_id,),
        )
        rows = await cursor.fetchall()

        total_cost = 0.0
        total_tokens_in = 0
        total_tokens_out = 0
        by_agent: dict[str, dict] = {}

        for (payload_json,) in rows:
            p = json.loads(payload_json) if payload_json else {}
            cost = p.get("cost", 0)
            t_in = p.get("tokens_in", 0)
            t_out = p.get("tokens_out", 0)
            agent = p.get("agent_id", "unknown")

            total_cost += cost
            total_tokens_in += t_in
            total_tokens_out += t_out

            if agent not in by_agent:
                by_agent[agent] = {"cost": 0.0, "tokens_in": 0, "tokens_out": 0, "model": ""}
            by_agent[agent]["cost"] += cost
            by_agent[agent]["tokens_in"] += t_in
            by_agent[agent]["tokens_out"] += t_out
            by_agent[agent]["model"] = p.get("model", by_agent[agent]["model"])

        return {
            "total_cost": total_cost,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "by_agent": by_agent,
        }

    async def delete_by_run(self, run_id: str) -> int:
        """Delete all events for a run. Returns count deleted."""
        cursor = await self._db.conn.execute(
            "DELETE FROM events WHERE run_id = ?", (run_id,)
        )
        await self._db.conn.commit()
        return cursor.rowcount
