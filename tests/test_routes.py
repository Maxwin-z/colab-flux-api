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


import time


def _wait_for_status(client, task_id, target, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/tasks/{task_id}", headers=AUTH)
        if r.status_code == 200 and r.json()["status"] in target:
            return r.json()
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not reach {target}")


def test_txt2img_requires_auth(test_app):
    client, _, _, _ = test_app
    r = client.post("/tasks/txt2img", json={"prompt": "x"})
    assert r.status_code == 401


def test_txt2img_validates_body(test_app):
    client, _, _, _ = test_app
    r = client.post("/tasks/txt2img", json={"prompt": "x", "width": 1000}, headers=AUTH)
    assert r.status_code == 422


def test_txt2img_submits_and_completes(test_app):
    client, store, _, _ = test_app
    r = client.post(
        "/tasks/txt2img",
        json={"prompt": "a cat", "width": 256, "height": 256},
        headers=AUTH,
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    task_id = body["task_id"]

    final = _wait_for_status(client, task_id, {"done", "failed"})
    assert final["status"] == "done", final
    assert final["image_url"] == f"/tasks/{task_id}/image"
