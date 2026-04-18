"""HTTP routes. Wired up by register_routes(app, ...) from main.py or tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI

from app.pipeline import PipelineProtocol
from app.schemas import HealthResponse
from app.store import TaskStore


def register_routes(
    app: FastAPI,
    *,
    store: TaskStore,
    queue: asyncio.Queue[str],
    pipeline: PipelineProtocol,
    output_dir: Path,
    input_dir: Path,
) -> None:
    """Attach all HTTP routes to the given FastAPI app."""

    @app.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse(
            status="ok",
            model_loaded=pipeline.is_loaded(),
            queue_depth=store.queue_depth(),
        )

    # /tasks/* routes and / static UI are added in later tasks.
    _state = {
        "store": store,
        "queue": queue,
        "pipeline": pipeline,
        "output_dir": output_dir,
        "input_dir": input_dir,
    }
    app.state.flux = _state
