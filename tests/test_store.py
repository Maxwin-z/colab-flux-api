from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.store import TaskRecord, TaskStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record(task_id: str, kind: str = "txt2img") -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        kind=kind,
        status="pending",
        params={"prompt": "x"},
        created_at=_now(),
        started_at=None,
        finished_at=None,
        result_path=None,
        error=None,
    )


@pytest.mark.asyncio
async def test_create_and_get():
    store = TaskStore()
    r = _record("a")
    await store.create(r)
    got = store.get("a")
    assert got is r


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    store = TaskStore()
    assert store.get("nope") is None


@pytest.mark.asyncio
async def test_set_status_updates_fields():
    store = TaskStore()
    await store.create(_record("a"))
    t = _now()
    await store.set_status("a", status="running", started_at=t)
    got = store.get("a")
    assert got.status == "running"
    assert got.started_at == t


@pytest.mark.asyncio
async def test_set_status_unknown_task_raises():
    store = TaskStore()
    with pytest.raises(KeyError):
        await store.set_status("nope", status="done")


@pytest.mark.asyncio
async def test_queue_position_counts_preceding_pending():
    store = TaskStore()
    for tid in ["a", "b", "c", "d"]:
        await store.create(_record(tid))
        await asyncio.sleep(0)  # ensure distinct timestamps
    # mark "b" running so it is no longer pending
    await store.set_status("b", status="running")
    assert store.queue_position("a") == 1
    assert store.queue_position("c") == 2  # a is ahead of c; b is running, not pending
    assert store.queue_position("d") == 3


@pytest.mark.asyncio
async def test_queue_position_none_when_not_pending():
    store = TaskStore()
    await store.create(_record("a"))
    await store.set_status("a", status="done")
    assert store.queue_position("a") is None


@pytest.mark.asyncio
async def test_queue_depth_counts_pending_and_running():
    store = TaskStore()
    await store.create(_record("a"))
    await store.create(_record("b"))
    await store.create(_record("c"))
    await store.set_status("a", status="running")
    await store.set_status("c", status="done")
    assert store.queue_depth() == 2  # a (running) + b (pending)
