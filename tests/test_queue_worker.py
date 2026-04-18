from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.pipeline import FakePipeline
from app.queue_worker import Worker
from app.store import TaskRecord, TaskStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pending(task_id: str, kind: str = "txt2img", params: dict | None = None) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        kind=kind,
        status="pending",
        params=params or {"prompt": "x", "width": 256, "height": 256,
                          "num_inference_steps": 4, "guidance_scale": 0.0, "seed": None},
        created_at=_now(),
    )


@pytest.mark.asyncio
async def test_worker_processes_pending_task(tmp_output_dir: Path):
    store = TaskStore()
    queue: asyncio.Queue[str] = asyncio.Queue()
    pipe = FakePipeline()
    worker = Worker(store=store, queue=queue, pipeline=pipe, output_dir=tmp_output_dir)

    await store.create(_pending("a"))
    await queue.put("a")

    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(queue.join(), timeout=2.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    rec = store.get("a")
    assert rec.status == "done"
    assert rec.started_at is not None
    assert rec.finished_at is not None
    assert rec.result_path == str(tmp_output_dir / "a.png")
    assert Path(rec.result_path).exists()


@pytest.mark.asyncio
async def test_worker_marks_failure_and_continues(tmp_output_dir: Path):
    store = TaskStore()
    queue: asyncio.Queue[str] = asyncio.Queue()
    # First task raises, second succeeds
    calls = {"n": 0}

    class FlakyPipeline(FakePipeline):
        def generate(self, kind, params):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return super().generate(kind, params)

    worker = Worker(store=store, queue=queue, pipeline=FlakyPipeline(), output_dir=tmp_output_dir)

    await store.create(_pending("a"))
    await store.create(_pending("b"))
    await queue.put("a")
    await queue.put("b")

    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(queue.join(), timeout=2.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert store.get("a").status == "failed"
    assert "RuntimeError" in store.get("a").error
    assert store.get("b").status == "done"


@pytest.mark.asyncio
async def test_worker_is_serial(tmp_output_dir: Path):
    """Two tasks in flight at the same time should never be observed."""
    store = TaskStore()
    queue: asyncio.Queue[str] = asyncio.Queue()
    running_overlap = {"max": 0, "current": 0}

    class SlowPipeline(FakePipeline):
        def generate(self, kind, params):
            running_overlap["current"] += 1
            running_overlap["max"] = max(running_overlap["max"], running_overlap["current"])
            # brief synchronous work — the worker runs generate inside to_thread
            import time
            time.sleep(0.05)
            running_overlap["current"] -= 1
            return super().generate(kind, params)

    worker = Worker(store=store, queue=queue, pipeline=SlowPipeline(), output_dir=tmp_output_dir)

    for tid in ["a", "b", "c"]:
        await store.create(_pending(tid))
        await queue.put(tid)

    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(queue.join(), timeout=3.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert running_overlap["max"] == 1
