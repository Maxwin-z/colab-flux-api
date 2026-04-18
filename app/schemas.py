"""Pydantic models for request validation and response shape."""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
from typing import Literal, Optional

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator

from app import config

Status = Literal["pending", "running", "done", "failed"]
Kind = Literal["txt2img", "img2img"]


def _validate_size(v: int) -> int:
    if v < config.MIN_SIZE or v > config.MAX_SIZE:
        raise ValueError(
            f"size must be in [{config.MIN_SIZE}, {config.MAX_SIZE}], got {v}"
        )
    if v % config.SIZE_MULTIPLE != 0:
        raise ValueError(f"size must be a multiple of {config.SIZE_MULTIPLE}, got {v}")
    return v


class TxtToImgRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=config.MAX_PROMPT_LEN)
    width: int = config.DEFAULT_WIDTH
    height: int = config.DEFAULT_HEIGHT
    num_inference_steps: int = Field(
        default=config.DEFAULT_STEPS,
        ge=config.MIN_STEPS,
        le=config.MAX_STEPS,
    )
    guidance_scale: float = config.DEFAULT_GUIDANCE_SCALE
    seed: Optional[int] = None

    @field_validator("width", "height")
    @classmethod
    def _check_size(cls, v: int) -> int:
        return _validate_size(v)


class ImgToImgRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=config.MAX_PROMPT_LEN)
    init_image: str  # base64 PNG/JPEG
    strength: float = Field(
        default=config.DEFAULT_STRENGTH,
        ge=config.MIN_STRENGTH,
        le=config.MAX_STRENGTH,
    )
    num_inference_steps: int = Field(
        default=config.DEFAULT_STEPS,
        ge=config.MIN_STEPS,
        le=config.MAX_STEPS,
    )
    guidance_scale: float = config.DEFAULT_GUIDANCE_SCALE
    seed: Optional[int] = None

    @field_validator("init_image")
    @classmethod
    def _check_image(cls, v: str) -> str:
        try:
            raw = base64.b64decode(v, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError("init_image is not valid base64") from e
        if len(raw) > config.MAX_INIT_IMAGE_BYTES:
            raise ValueError(
                f"init_image decoded size exceeds {config.MAX_INIT_IMAGE_BYTES} bytes"
            )
        try:
            with Image.open(BytesIO(raw)) as img:
                img.verify()
        except (UnidentifiedImageError, OSError) as e:
            raise ValueError("init_image is not a readable PNG/JPEG") from e
        return v


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: Status


class TaskStatusResponse(BaseModel):
    task_id: str
    kind: Kind
    status: Status
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    queue_position: Optional[int] = None
    image_url: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    queue_depth: int
