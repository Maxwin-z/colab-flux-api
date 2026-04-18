"""HTTP routes. Wired up by register_routes(app, ...) from main.py or tests."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi import status as http_status
from fastapi.responses import FileResponse

from app.auth import require_token
from app.pipeline import PipelineProtocol
from app.schemas import HealthResponse, ImgToImgRequest, TaskStatusResponse, TaskSubmitResponse, TxtToImgRequest
from app.store import TaskRecord, TaskStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


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

    @app.post(
        "/tasks/txt2img",
        response_model=TaskSubmitResponse,
        status_code=http_status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_token)],
    )
    async def submit_txt2img(req: TxtToImgRequest) -> TaskSubmitResponse:
        task_id = uuid4().hex
        params = req.model_dump()
        record = TaskRecord(
            task_id=task_id,
            kind="txt2img",
            status="pending",
            params=params,
            created_at=_now(),
        )
        await store.create(record)
        await queue.put(task_id)
        return TaskSubmitResponse(task_id=task_id, status="pending")

    @app.get(
        "/tasks/{task_id}",
        response_model=TaskStatusResponse,
        dependencies=[Depends(require_token)],
    )
    async def get_task(task_id: str) -> TaskStatusResponse:
        rec = store.get(task_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="not found")
        return TaskStatusResponse(
            task_id=rec.task_id,
            kind=rec.kind,
            status=rec.status,
            created_at=rec.created_at.isoformat(),
            started_at=rec.started_at.isoformat() if rec.started_at else None,
            finished_at=rec.finished_at.isoformat() if rec.finished_at else None,
            queue_position=store.queue_position(task_id) if rec.status == "pending" else None,
            image_url=f"/tasks/{rec.task_id}/image" if rec.status == "done" else None,
            error=rec.error,
        )

    @app.post(
        "/tasks/img2img",
        response_model=TaskSubmitResponse,
        status_code=http_status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_token)],
    )
    async def submit_img2img(req: ImgToImgRequest) -> TaskSubmitResponse:
        task_id = uuid4().hex
        raw = base64.b64decode(req.init_image, validate=True)
        init_path = input_dir / f"{task_id}.png"
        init_path.write_bytes(raw)

        params = req.model_dump()
        params.pop("init_image", None)
        params["init_image_path"] = str(init_path)

        record = TaskRecord(
            task_id=task_id,
            kind="img2img",
            status="pending",
            params=params,
            created_at=_now(),
        )
        await store.create(record)
        await queue.put(task_id)
        return TaskSubmitResponse(task_id=task_id, status="pending")

    @app.get("/tasks/{task_id}/image", dependencies=[Depends(require_token)])
    async def download_image(task_id: str):
        rec = store.get(task_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="not found")
        if rec.status != "done" or not rec.result_path:
            raise HTTPException(status_code=409, detail=f"task status is {rec.status}")
        return FileResponse(rec.result_path, media_type="image/png", filename=f"{task_id}.png")

    _static_dir = Path(__file__).parent / "static"

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(_static_dir / "index.html", media_type="text/html")

    _state = {
        "store": store,
        "queue": queue,
        "pipeline": pipeline,
        "output_dir": output_dir,
        "input_dir": input_dir,
    }
    app.state.flux = _state
