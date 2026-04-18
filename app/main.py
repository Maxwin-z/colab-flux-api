"""Application factory. Wires store, queue, worker, pipeline, and routes."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI

from app import config
from app.auth import set_expected_token
from app.pipeline import FakePipeline, FluxPipelineHolder, PipelineProtocol
from app.queue_worker import Worker
from app.routes import register_routes
from app.store import TaskStore

logger = logging.getLogger(__name__)


def create_app(
    *,
    use_fake_pipeline: bool = False,
    token: Optional[str] = None,
    output_dir: Optional[Path] = None,
    input_dir: Optional[Path] = None,
) -> FastAPI:
    """Build a FastAPI app. For production, call with defaults (use_fake_pipeline=False)."""

    resolved_token = token or os.environ.get("FLUX_TOKEN") or config.generate_token()
    set_expected_token(resolved_token)

    out_dir = output_dir or config.OUTPUT_DIR
    in_dir = input_dir or config.INPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    in_dir.mkdir(parents=True, exist_ok=True)

    store = TaskStore()
    queue: asyncio.Queue[str] = asyncio.Queue()

    pipeline: PipelineProtocol
    pipeline = FakePipeline() if use_fake_pipeline else FluxPipelineHolder()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not use_fake_pipeline:
            logger.info("loading FLUX pipeline...")
            await asyncio.to_thread(pipeline.load)
            logger.info("FLUX pipeline loaded")
        worker = Worker(store=store, queue=queue, pipeline=pipeline, output_dir=out_dir)
        task = asyncio.create_task(worker.run(), name="flux-worker")
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="FLUX Image Generator", lifespan=lifespan)
    register_routes(
        app,
        store=store,
        queue=queue,
        pipeline=pipeline,
        output_dir=out_dir,
        input_dir=in_dir,
    )
    app.state.token = resolved_token
    return app


# For `uvicorn app.main:app` — only create if /content is available (Colab).
# Otherwise callers (including tests) must use create_app() themselves.
if Path("/content").exists() or os.environ.get("FLUX_TOKEN"):
    app = create_app()
