from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import set_expected_token
from app.pipeline import FakePipeline
from app.queue_worker import Worker
from app.routes import register_routes
from app.store import TaskStore


TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def test_app(tmp_path: Path):
    """Build a FastAPI app with a FakePipeline and a worker started via lifespan.

    Using `with TestClient(app) as client:` triggers the lifespan, which launches
    the worker on the SAME event loop that serves HTTP requests. This is essential
    — asyncio.Queue and asyncio.Lock must be used from a single loop.
    """
    set_expected_token(TOKEN)
    store = TaskStore()
    queue: asyncio.Queue[str] = asyncio.Queue()
    pipeline = FakePipeline()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    inputs = tmp_path / "inputs"
    inputs.mkdir()

    worker = Worker(store=store, queue=queue, pipeline=pipeline, output_dir=outputs)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(worker.run(), name="flux-worker-test")
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(lifespan=lifespan)
    register_routes(
        app,
        store=store,
        queue=queue,
        pipeline=pipeline,
        output_dir=outputs,
        input_dir=inputs,
    )

    with TestClient(app) as client:
        yield client, store, queue, outputs


def test_healthz_does_not_require_auth(test_app):
    client, _, _, _ = test_app
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["queue_depth"] == 0
