"""WebSocket endpoint: task submission + subscription multiplexed on one connection.

Protocol summary (see docs/superpowers/specs/2026-04-18-ws-task-protocol-design.md):

Client → server:
  submit       — create a new task; the sender is implicitly subscribed
  subscribe    — subscribe to an existing task_id
  unsubscribe  — cancel a subscription (idempotent)

Server → client:
  submitted    — reply to submit with the generated task_id
  state        — full TaskRecord snapshot (sent on subscribe + on every set_status)
  error        — validation / not_found / internal error
"""

from __future__ import annotations

import asyncio
import base64
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.schemas import ImgToImgRequest, TxtToImgRequest
from app.store import TaskRecord, TaskStore
from app.ws_hub import SubscriptionHub

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def to_snapshot_dict(rec: TaskRecord, *, queue_position: int | None = None) -> dict[str, Any]:
    """Serialize a TaskRecord to the wire shape used by both WS `state` events
    and (indirectly) REST TaskStatusResponse.
    """
    return {
        "task_id": rec.task_id,
        "kind": rec.kind,
        "status": rec.status,
        "created_at": rec.created_at.isoformat(),
        "started_at": rec.started_at.isoformat() if rec.started_at else None,
        "finished_at": rec.finished_at.isoformat() if rec.finished_at else None,
        "queue_position": queue_position,
        "image_url": f"/tasks/{rec.task_id}/image" if rec.status == "done" else None,
        "error": rec.error,
    }


def _error(req_id: Any, code: str, message: str) -> dict[str, Any]:
    return {"type": "error", "req_id": req_id, "code": code, "message": message}


async def _handle_submit(
    ws: WebSocket,
    msg: dict[str, Any],
    hub: SubscriptionHub,
    store: TaskStore,
    queue: asyncio.Queue[str],
    input_dir: Path,
) -> None:
    req_id = msg.get("req_id")
    kind = msg.get("kind")
    params = msg.get("params") or {}

    if kind == "txt2img":
        try:
            validated = TxtToImgRequest(**params)
        except ValidationError as e:
            await ws.send_json(_error(req_id, "validation", e.errors()[0].get("msg", "invalid params")))
            return
        task_id = uuid4().hex
        record_params = validated.model_dump()
    elif kind == "img2img":
        try:
            validated = ImgToImgRequest(**params)
        except ValidationError as e:
            await ws.send_json(_error(req_id, "validation", e.errors()[0].get("msg", "invalid params")))
            return
        task_id = uuid4().hex
        raw = base64.b64decode(validated.init_image, validate=True)
        init_path = input_dir / f"{task_id}.png"
        init_path.write_bytes(raw)
        record_params = validated.model_dump()
        record_params.pop("init_image", None)
        record_params["init_image_path"] = str(init_path)
    else:
        await ws.send_json(_error(req_id, "validation", f"unknown kind: {kind!r}"))
        return

    record = TaskRecord(
        task_id=task_id,
        kind=kind,
        status="pending",
        params=record_params,
        created_at=_now(),
    )
    await store.create(record)

    # Subscribe BEFORE enqueueing, so we cannot miss the worker's first state change.
    await hub.subscribe(task_id, ws)

    await ws.send_json({"type": "submitted", "req_id": req_id, "task_id": task_id})
    await ws.send_json({
        "type": "state",
        **to_snapshot_dict(record, queue_position=store.queue_position(task_id)),
    })

    await queue.put(task_id)


async def _handle_subscribe(
    ws: WebSocket,
    msg: dict[str, Any],
    hub: SubscriptionHub,
    store: TaskStore,
) -> None:
    req_id = msg.get("req_id")
    task_id = msg.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        await ws.send_json(_error(req_id, "validation", "task_id required"))
        return

    rec = store.get(task_id)
    if rec is None:
        await ws.send_json(_error(req_id, "not_found", f"task {task_id} not found"))
        return

    await hub.subscribe(task_id, ws)
    queue_position = store.queue_position(task_id) if rec.status == "pending" else None
    await ws.send_json({"type": "state", **to_snapshot_dict(rec, queue_position=queue_position)})

    if rec.status in ("done", "failed"):
        await hub.unsubscribe(task_id, ws)


async def _handle_unsubscribe(
    ws: WebSocket,
    msg: dict[str, Any],
    hub: SubscriptionHub,
) -> None:
    task_id = msg.get("task_id")
    if isinstance(task_id, str) and task_id:
        await hub.unsubscribe(task_id, ws)


async def ws_endpoint(
    ws: WebSocket,
    *,
    hub: SubscriptionHub,
    store: TaskStore,
    queue: asyncio.Queue[str],
    input_dir: Path,
    expected_token: str,
) -> None:
    await ws.accept()
    if ws.query_params.get("token") != expected_token:
        # Accept-then-close so browser's onclose event sees the 4401 code.
        # (Closing before accept results in an HTTP 4xx during handshake, and
        # browsers cannot surface an application close code in that path.)
        await ws.close(code=4401)
        return

    # Wrap `set_status` so that every state transition for tasks that were
    # originally terminal-on-subscribe gets a clean auto-unsub. This is handled
    # inside hub.publish for in-flight subscriptions; here we just need the
    # auto-unsub after publishing a terminal state. See publish_terminal_guard.
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except WebSocketDisconnect:
                break

            if not isinstance(msg, dict):
                await ws.send_json(_error(None, "validation", "message must be a JSON object"))
                continue

            t = msg.get("type")
            try:
                if t == "submit":
                    await _handle_submit(ws, msg, hub, store, queue, input_dir)
                elif t == "subscribe":
                    await _handle_subscribe(ws, msg, hub, store)
                elif t == "unsubscribe":
                    await _handle_unsubscribe(ws, msg, hub)
                else:
                    await ws.send_json(_error(msg.get("req_id"), "validation", f"unknown type {t!r}"))
            except WebSocketDisconnect:
                break
            except Exception:
                logger.error("ws handler crashed:\n%s", traceback.format_exc())
                try:
                    await ws.send_json(_error(msg.get("req_id"), "internal", "handler error"))
                except Exception:
                    break
    finally:
        await hub.drop_connection(ws)


def register_ws(
    app: FastAPI,
    *,
    hub: SubscriptionHub,
    store: TaskStore,
    queue: asyncio.Queue[str],
    input_dir: Path,
    expected_token: str,
) -> None:
    """Attach the /ws endpoint to the given FastAPI app."""

    @app.websocket("/ws")
    async def _ws(ws: WebSocket) -> None:
        await ws_endpoint(
            ws,
            hub=hub,
            store=store,
            queue=queue,
            input_dir=input_dir,
            expected_token=expected_token,
        )
