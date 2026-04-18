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


import base64
from io import BytesIO
from PIL import Image


def _make_b64_image() -> str:
    buf = BytesIO()
    Image.new("RGB", (256, 256), color="red").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_img2img_requires_auth(test_app):
    client, _, _, _ = test_app
    r = client.post("/tasks/img2img", json={"prompt": "x", "init_image": _make_b64_image()})
    assert r.status_code == 401


def test_img2img_rejects_invalid_image(test_app):
    client, _, _, _ = test_app
    r = client.post(
        "/tasks/img2img",
        json={"prompt": "x", "init_image": base64.b64encode(b"not an image").decode("ascii")},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_img2img_submits_saves_init_image_and_completes(test_app, tmp_path):
    client, store, _, _ = test_app
    r = client.post(
        "/tasks/img2img",
        json={"prompt": "x", "init_image": _make_b64_image(), "strength": 0.5},
        headers=AUTH,
    )
    assert r.status_code == 202
    task_id = r.json()["task_id"]

    final = _wait_for_status(client, task_id, {"done", "failed"})
    assert final["status"] == "done", final

    rec = store.get(task_id)
    assert "init_image_path" in rec.params
    # init_image raw base64 should NOT be retained in memory
    assert "init_image" not in rec.params
    from pathlib import Path as _P
    assert _P(rec.params["init_image_path"]).exists()


def test_status_response_has_expected_fields_when_pending(test_app):
    client, _, _, _ = test_app
    # Submit many tasks so at least one is still pending when we query
    ids = []
    for _ in range(5):
        r = client.post("/tasks/txt2img", json={"prompt": "x", "width": 256, "height": 256}, headers=AUTH)
        ids.append(r.json()["task_id"])
    # Query the last one: might be pending or running
    r = client.get(f"/tasks/{ids[-1]}", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == ids[-1]
    assert body["kind"] == "txt2img"
    assert set(body.keys()) == {
        "task_id", "kind", "status", "created_at", "started_at",
        "finished_at", "queue_position", "image_url", "error",
    }


def test_status_404_for_unknown(test_app):
    client, _, _, _ = test_app
    r = client.get("/tasks/does-not-exist", headers=AUTH)
    assert r.status_code == 404
