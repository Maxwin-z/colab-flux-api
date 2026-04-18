"""Single async worker consuming task IDs from an asyncio.Queue."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.pipeline import PipelineProtocol
from app.store import TaskStore

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Worker:
    def __init__(
        self,
        store: TaskStore,
        queue: asyncio.Queue[str],
        pipeline: PipelineProtocol,
        output_dir: Path,
    ) -> None:
        self.store = store
        self.queue = queue
        self.pipeline = pipeline
        self.output_dir = output_dir

    async def run(self) -> None:
        """Process tasks until cancelled. Never crashes on task failure."""
        while True:
            task_id = await self.queue.get()
            try:
                await self._process(task_id)
            finally:
                self.queue.task_done()

    async def _process(self, task_id: str) -> None:
        record = self.store.get(task_id)
        if record is None:
            logger.warning("task %s not found in store, skipping", task_id)
            return

        await self.store.set_status(task_id, status="running", started_at=_now())
        try:
            image = await asyncio.to_thread(
                self.pipeline.generate, record.kind, record.params
            )
            out_path = self.output_dir / f"{task_id}.png"
            await asyncio.to_thread(image.save, str(out_path), "PNG")
            await self.store.set_status(
                task_id,
                status="done",
                finished_at=_now(),
                result_path=str(out_path),
            )
        except Exception as e:
            logger.error("task %s failed:\n%s", task_id, traceback.format_exc())
            await self.store.set_status(
                task_id,
                status="failed",
                finished_at=_now(),
                error=f"{type(e).__name__}: {str(e)[:500]}",
            )
            # Best-effort GPU cache clear without importing torch at module level.
            _try_empty_cuda_cache()


def _try_empty_cuda_cache() -> None:
    try:
        import torch  # imported lazily — not required in tests

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
