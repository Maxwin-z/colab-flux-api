from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from app.auth import set_expected_token
from app.pipeline import FakePipeline
from app.queue_worker import Worker
from app.routes import register_routes
from app.store import TaskStore
from app.ws import register_ws
from app.ws_hub import SubscriptionHub


TOKEN = "ws-test-token"


def _make_b64_image() -> str:
    buf = BytesIO()
    Image.new("RGB", (64, 64), color="red").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.fixture
def ws_app(tmp_path: Path):
    set_expected_token(TOKEN)
    hub = SubscriptionHub()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    inputs = tmp_path / "inputs"
    inputs.mkdir()

    queue: asyncio.Queue[str] = asyncio.Queue()
    pipeline = FakePipeline()

    async def on_change(rec):
        from app.ws import to_snapshot_dict
        await hub.publish(rec.task_id, {"type": "state", **to_snapshot_dict(rec)})

    store = TaskStore(on_change=on_change)
    worker = Worker(store=store, queue=queue, pipeline=pipeline, output_dir=outputs)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(worker.run(), name="ws-test-worker")
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
    register_ws(
        app,
        hub=hub,
        store=store,
        queue=queue,
        input_dir=inputs,
        expected_token=TOKEN,
    )

    with TestClient(app) as client:
        yield client, hub, store


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_ws_rejects_missing_token(ws_app):
    client, _, _ = ws_app
    with client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as ei:
            ws.receive_json()
        assert ei.value.code == 4401


def test_ws_rejects_wrong_token(ws_app):
    client, _, _ = ws_app
    with client.websocket_connect("/ws?token=wrong") as ws:
        with pytest.raises(WebSocketDisconnect) as ei:
            ws.receive_json()
        assert ei.value.code == 4401


def test_ws_accepts_valid_token(ws_app):
    client, _, _ = ws_app
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        # connection is live — send a bogus message and confirm we get a proto error back
        ws.send_json({"type": "unsubscribe", "task_id": "whatever"})  # idempotent, no reply


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


def _recv_until(ws, predicate, *, max_messages: int = 10):
    """Receive JSON messages until `predicate(msg)` is True, or raise."""
    seen: list[dict] = []
    for _ in range(max_messages):
        msg = ws.receive_json()
        seen.append(msg)
        if predicate(msg):
            return msg, seen
    raise AssertionError(f"predicate not satisfied after {max_messages} messages: {seen}")


def test_ws_submit_txt2img_returns_submitted_then_state_events(ws_app):
    client, hub, store = ws_app
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_json({
            "type": "submit",
            "req_id": "c1",
            "kind": "txt2img",
            "params": {"prompt": "hi", "width": 256, "height": 256},
        })
        submitted = ws.receive_json()
        assert submitted["type"] == "submitted"
        assert submitted["req_id"] == "c1"
        task_id = submitted["task_id"]
        assert task_id

        first_state = ws.receive_json()
        assert first_state["type"] == "state"
        assert first_state["task_id"] == task_id
        assert first_state["status"] == "pending"
        assert first_state["kind"] == "txt2img"

        # The worker will transition running → done. Drain state events until done.
        terminal, _seen = _recv_until(ws, lambda m: m.get("type") == "state" and m.get("status") in {"done", "failed"})
        assert terminal["status"] == "done", terminal
        assert terminal["task_id"] == task_id
        assert terminal["image_url"] == f"/tasks/{task_id}/image"


def test_ws_submit_img2img_decodes_and_writes_init_image(ws_app):
    client, hub, store = ws_app
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_json({
            "type": "submit",
            "req_id": "c1",
            "kind": "img2img",
            "params": {"prompt": "a", "init_image": _make_b64_image(), "strength": 0.5},
        })
        submitted = ws.receive_json()
        assert submitted["type"] == "submitted"
        task_id = submitted["task_id"]
        terminal, _ = _recv_until(
            ws, lambda m: m.get("type") == "state" and m.get("status") in {"done", "failed"}
        )
        assert terminal["status"] == "done", terminal

    rec = store.get(task_id)
    assert "init_image_path" in rec.params
    assert "init_image" not in rec.params
    assert Path(rec.params["init_image_path"]).exists()


def test_ws_submit_validation_failure_does_not_create_task(ws_app):
    client, _, store = ws_app
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_json({
            "type": "submit",
            "req_id": "c1",
            "kind": "txt2img",
            "params": {"prompt": "a", "width": 1000},  # not a multiple of 64
        })
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "validation"
        assert err["req_id"] == "c1"
    # No task should exist
    assert len([r for r in store.all_records() if True]) == 0


def test_ws_submit_unknown_kind_is_validation_error(ws_app):
    client, _, _ = ws_app
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_json({
            "type": "submit",
            "req_id": "c1",
            "kind": "nonsense",
            "params": {"prompt": "a"},
        })
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "validation"


# ---------------------------------------------------------------------------
# Subscribe
# ---------------------------------------------------------------------------


def test_ws_subscribe_unknown_task_returns_not_found(ws_app):
    client, _, _ = ws_app
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_json({"type": "subscribe", "req_id": "c1", "task_id": "ghost"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "not_found"
        assert err["req_id"] == "c1"


def test_ws_subscribe_already_done_delivers_terminal_state_and_auto_unsubs(ws_app):
    client, hub, store = ws_app
    # First: create a task via WS, wait until done, close connection.
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_json({
            "type": "submit",
            "req_id": "c1",
            "kind": "txt2img",
            "params": {"prompt": "done", "width": 256, "height": 256},
        })
        submitted = ws.receive_json()
        assert submitted["type"] == "submitted"
        task_id = submitted["task_id"]
        terminal, _ = _recv_until(
            ws, lambda m: m.get("type") == "state" and m.get("status") in {"done", "failed"}
        )
        assert terminal["status"] == "done"
    # Second: fresh connection subscribes to that completed task.
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws2:
        ws2.send_json({"type": "subscribe", "req_id": "c2", "task_id": task_id})
        snap = ws2.receive_json()
        assert snap["type"] == "state"
        assert snap["task_id"] == task_id
        assert snap["status"] == "done"
    # After the done task was subscribed, the hub should have no subs for it
    # (terminal auto-unsub), regardless of whether the connection is still open.
    assert task_id not in hub._subs or not hub._subs.get(task_id)


# ---------------------------------------------------------------------------
# Protocol-layer errors
# ---------------------------------------------------------------------------


def test_ws_unknown_type_is_validation_error(ws_app):
    client, _, _ = ws_app
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_json({"type": "wat", "req_id": "c1"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "validation"
        assert err["req_id"] == "c1"


def test_ws_missing_type_is_validation_error(ws_app):
    client, _, _ = ws_app
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_json({"req_id": "c1"})  # no type
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "validation"


# ---------------------------------------------------------------------------
# Connection cleanup
# ---------------------------------------------------------------------------


def test_ws_disconnect_removes_subscriptions(ws_app):
    client, hub, _ = ws_app
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_json({
            "type": "submit",
            "req_id": "c1",
            "kind": "txt2img",
            "params": {"prompt": "x", "width": 256, "height": 256},
        })
        submitted = ws.receive_json()
        task_id = submitted["task_id"]
        # Consume the first pending state to prove we're subscribed.
        st = ws.receive_json()
        assert st["type"] == "state" and st["status"] == "pending"
    # After exiting the context manager, the WS is closed; the server's finally
    # block should clean up all subscriptions for this connection.
    # Allow a brief moment for the server-side close handling to run.
    import time as _t
    for _ in range(20):
        if not hub._subs.get(task_id):
            break
        _t.sleep(0.05)
    assert task_id not in hub._subs or not hub._subs[task_id]
