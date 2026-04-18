"""In-memory task store, guarded by an asyncio.Lock for writes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal, Optional


Status = Literal["pending", "running", "done", "failed"]
Kind = Literal["txt2img", "img2img"]

OnChange = Callable[["TaskRecord"], Awaitable[None]]


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
    """Dictionary-backed task store. Writes are serialized with an asyncio.Lock.

    When `on_change` is supplied, it is awaited once per `set_status` with the
    updated record. The callback runs OUTSIDE the store lock so a slow broadcast
    cannot block subsequent mutations. `create` does not invoke on_change — the
    initial "pending" snapshot is the submit handler's responsibility.
    """

    def __init__(self, on_change: Optional[OnChange] = None) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()
        self._on_change = on_change

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
        if self._on_change is not None:
            await self._on_change(record)

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
