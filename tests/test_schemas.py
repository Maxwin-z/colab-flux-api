from __future__ import annotations

import base64
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from app.schemas import (
    HealthResponse,
    ImgToImgRequest,
    TaskStatusResponse,
    TaskSubmitResponse,
    TxtToImgRequest,
)


def _tiny_png_b64() -> str:
    buf = BytesIO()
    Image.new("RGB", (64, 64), color=(200, 100, 50)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class TestTxtToImgRequest:
    def test_defaults(self):
        req = TxtToImgRequest(prompt="a cat")
        assert req.width == 1024
        assert req.height == 1024
        assert req.num_inference_steps == 4
        assert req.guidance_scale == 0.0
        assert req.seed is None

    def test_empty_prompt_rejected(self):
        with pytest.raises(ValidationError):
            TxtToImgRequest(prompt="")

    def test_width_not_multiple_of_64_rejected(self):
        with pytest.raises(ValidationError):
            TxtToImgRequest(prompt="x", width=1000)

    def test_size_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            TxtToImgRequest(prompt="x", width=128)

    def test_size_above_maximum_rejected(self):
        with pytest.raises(ValidationError):
            TxtToImgRequest(prompt="x", width=2048)

    def test_steps_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            TxtToImgRequest(prompt="x", num_inference_steps=0)
        with pytest.raises(ValidationError):
            TxtToImgRequest(prompt="x", num_inference_steps=20)


class TestImgToImgRequest:
    def test_accepts_valid_base64_png(self):
        req = ImgToImgRequest(prompt="x", init_image=_tiny_png_b64())
        assert req.strength == 0.7

    def test_rejects_invalid_base64(self):
        with pytest.raises(ValidationError):
            ImgToImgRequest(prompt="x", init_image="not-base64!!!")

    def test_rejects_non_image_bytes(self):
        garbage = base64.b64encode(b"not an image at all").decode("ascii")
        with pytest.raises(ValidationError):
            ImgToImgRequest(prompt="x", init_image=garbage)

    def test_rejects_oversized(self):
        big_b64 = base64.b64encode(b"\x00" * (10 * 1024 * 1024 + 1)).decode("ascii")
        with pytest.raises(ValidationError):
            ImgToImgRequest(prompt="x", init_image=big_b64)

    def test_strength_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            ImgToImgRequest(prompt="x", init_image=_tiny_png_b64(), strength=1.5)


class TestResponses:
    def test_task_submit_response_shape(self):
        r = TaskSubmitResponse(task_id="abc", status="pending")
        assert r.model_dump() == {"task_id": "abc", "status": "pending"}

    def test_status_response_optional_fields(self):
        r = TaskStatusResponse(
            task_id="abc",
            kind="txt2img",
            status="pending",
            created_at="2026-04-18T12:00:00Z",
            started_at=None,
            finished_at=None,
            queue_position=3,
            image_url=None,
            error=None,
        )
        assert r.status == "pending"
        assert r.queue_position == 3

    def test_health_response_shape(self):
        r = HealthResponse(status="ok", model_loaded=True, queue_depth=0)
        assert r.model_dump() == {"status": "ok", "model_loaded": True, "queue_depth": 0}
