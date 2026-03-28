"""Immutable data models for persistent storage."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import Enum

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    class StrEnum(str, Enum):
        """Polyfill for Python 3.10."""


class RunStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True)
class RunRecord:
    """Immutable snapshot of a pipeline run."""

    id: str
    name: str = ""
    status: str = RunStatus.ACTIVE
    started_at: str = ""
    completed_at: str = ""
    total_cost: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    agent_count: int = 0
    event_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_cost": self.total_cost,
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "agent_count": self.agent_count,
            "event_count": self.event_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row: tuple) -> RunRecord:
        return cls(
            id=row[0],
            name=row[1],
            status=row[2],
            started_at=row[3],
            completed_at=row[4] or "",
            total_cost=row[5],
            total_tokens_in=row[6],
            total_tokens_out=row[7],
            agent_count=row[8],
            event_count=row[9],
            metadata=json.loads(row[10]) if row[10] else {},
        )


@dataclass(frozen=True)
class EventRecord:
    """Immutable snapshot of a persisted event."""

    id: str
    run_id: str
    type: str
    timestamp: str
    source_framework: str = ""
    payload: dict = field(default_factory=dict)
    agent_id: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "type": self.type,
            "timestamp": self.timestamp,
            "source_framework": self.source_framework,
            "payload": self.payload,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_row(cls, row: tuple) -> EventRecord:
        return cls(
            id=row[0],
            run_id=row[1],
            type=row[2],
            timestamp=row[3],
            source_framework=row[4] or "",
            payload=json.loads(row[5]) if row[5] else {},
            agent_id=row[6] or "",
        )
