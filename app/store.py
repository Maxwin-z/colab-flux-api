"""In-memory task store, guarded by an asyncio.Lock for writes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional


Status = Literal["pending", "running", "done", "failed"]
Kind = Literal["txt2img", "img2img"]


@dataclass
class TaskRecord:
    task_id: str
    kind: Kind
    status: Status
    params: dict[str, Any]
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result_path: Optional[str] = None
    error: Optional[str] = None


class TaskStore:
    """Dictionary-backed task store. Writes are serialized with an asyncio.Lock."""

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: TaskRecord) -> None:
        async with self._lock:
            self._records[record.task_id] = record

    def get(self, task_id: str) -> Optional[TaskRecord]:
        return self._records.get(task_id)

    async def set_status(self, task_id: str, **updates: Any) -> None:
        async with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise KeyError(task_id)
            for k, v in updates.items():
                if not hasattr(record, k):
                    raise AttributeError(f"TaskRecord has no field {k!r}")
                setattr(record, k, v)

    def queue_position(self, task_id: str) -> Optional[int]:
        """1-based position among pending tasks, ordered by created_at.

        Returns None if the task is not pending.
        """
        target = self._records.get(task_id)
        if target is None or target.status != "pending":
            return None
        ahead = sum(
            1
            for r in self._records.values()
            if r.status == "pending" and r.created_at <= target.created_at and r.task_id != target.task_id
        )
        return ahead + 1

    def queue_depth(self) -> int:
        """Count tasks that are pending or running (i.e., occupying the queue)."""
        return sum(1 for r in self._records.values() if r.status in ("pending", "running"))

    def all_records(self) -> list[TaskRecord]:
        return list(self._records.values())
