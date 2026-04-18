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


@pytest.mark.asyncio
async def test_on_change_is_invoked_with_updated_record():
    calls: list[tuple[str, str]] = []

    async def on_change(rec):
        calls.append((rec.task_id, rec.status))

    store = TaskStore(on_change=on_change)
    await store.create(_record("a"))
    # create does NOT invoke on_change (initial "pending" snapshot is sent by ws submit handler)
    assert calls == []

    await store.set_status("a", status="running")
    await store.set_status("a", status="done")
    assert calls == [("a", "running"), ("a", "done")]


@pytest.mark.asyncio
async def test_on_change_runs_outside_store_lock():
    """The callback must run outside _lock so a slow callback doesn't block
    subsequent set_status calls from the same loop."""
    store_box: dict[str, TaskStore] = {}
    observed_during_callback: list[str] = []

    async def on_change(rec):
        # While inside the callback, issuing another mutate must not deadlock.
        await store_box["store"].set_status("b", status="running") if rec.task_id == "a" else None
        observed_during_callback.append(rec.task_id)

    store = TaskStore(on_change=on_change)
    store_box["store"] = store
    await store.create(_record("a"))
    await store.create(_record("b"))
    # This must complete without hanging; the nested set_status("b", ...) in
    # the callback only works because on_change is outside the lock.
    await asyncio.wait_for(store.set_status("a", status="running"), timeout=1.0)
    assert "a" in observed_during_callback
    assert "b" in observed_during_callback
    assert store.get("b").status == "running"


@pytest.mark.asyncio
async def test_on_change_none_is_default():
    # Default behavior: no callback, no error.
    store = TaskStore()
    await store.create(_record("a"))
    await store.set_status("a", status="running")  # must not raise
