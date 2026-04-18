# Colab FLUX Image API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python script that runs FLUX.1 [schnell] on Colab L4, exposes a small REST API + single-page web UI for txt2img / img2img, and tunnels publicly via TryCloudflare.

**Architecture:** FastAPI + single asyncio worker consuming an `asyncio.Queue`, calling a lazily-loaded `FluxPipelineHolder`. In-memory `TaskStore`; images written to `/content/outputs/{id}.png`. Static `index.html` served at `/` with browser-side history in `localStorage`. Entry script `run_colab.py` generates a random Bearer token, launches `cloudflared` as a subprocess, prints the public URL, then runs uvicorn.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, `diffusers` + `torch` (bfloat16 on CUDA), PIL, uvicorn, vanilla HTML/CSS/JS (no bundler), `cloudflared` binary.

**Reference spec:** `docs/superpowers/specs/2026-04-18-colab-flux-image-api-design.md`

---

## File Structure

```
llm-image-generator/
├── .gitignore
├── README.md                           # Colab run instructions
├── pyproject.toml                      # only if we go that way; we use plain requirements files
├── requirements.txt                    # Colab deps (includes torch/diffusers)
├── requirements-dev.txt                # local dev/test deps (no GPU deps)
├── run_colab.py                        # entry: token + cloudflared + uvicorn
├── app/
│   ├── __init__.py
│   ├── main.py                         # FastAPI app + lifespan wiring
│   ├── config.py                       # paths, defaults, token generation
│   ├── auth.py                         # Bearer token dependency
│   ├── schemas.py                      # Pydantic request/response models
│   ├── store.py                        # TaskStore, TaskRecord
│   ├── queue_worker.py                 # worker_loop
│   ├── pipeline.py                     # FluxPipelineHolder + PipelineProtocol + FakePipeline
│   ├── routes.py                       # /tasks/*, /healthz, /
│   └── static/
│       └── index.html                  # single-page UI
├── tests/
│   ├── __init__.py
│   ├── conftest.py                     # pytest fixtures (tmp dirs, fake pipeline, client)
│   ├── test_config.py
│   ├── test_schemas.py
│   ├── test_store.py
│   ├── test_auth.py
│   ├── test_queue_worker.py
│   └── test_routes.py
└── docs/
    └── superpowers/
        ├── specs/2026-04-18-colab-flux-image-api-design.md
        └── plans/2026-04-18-colab-flux-image-api.md   # this file
```

**Module boundaries:**
- `pipeline.py` is the only module importing `torch` / `diffusers`. Everything else is pure protocol-level and can be unit-tested on a Mac without a GPU.
- `routes.py` takes its `TaskStore`, `asyncio.Queue`, and pipeline protocol via `main.py`'s app state, so tests can substitute a `FakePipeline`.
- `static/index.html` is a single self-contained file (inline CSS + inline JS + external fetches only to same-origin `/tasks/*`).

---

## Task 0: Project Scaffolding & Git

**Files:**
- Create: `.gitignore`, `README.md`, `requirements.txt`, `requirements-dev.txt`
- Create: `app/__init__.py`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Initialize git and create directories**

```bash
cd /Users/maxwin/workspace/colab/llm-image-generator
git init -b main
mkdir -p app/static tests
touch app/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/
.coverage
htmlcov/
.DS_Store
/content/
outputs/
inputs/
*.egg-info/
```

- [ ] **Step 3: Write `requirements.txt` (Colab deps)**

```
torch>=2.2
diffusers>=0.30
transformers>=4.44
accelerate>=0.33
sentencepiece
fastapi>=0.115
uvicorn[standard]>=0.30
pillow>=10
pydantic>=2
```

- [ ] **Step 4: Write `requirements-dev.txt` (local test deps)**

```
fastapi>=0.115
uvicorn[standard]>=0.30
pillow>=10
pydantic>=2
pytest>=8
pytest-asyncio>=0.23
httpx>=0.27
```

Note: `torch`, `diffusers`, `transformers`, `accelerate`, `sentencepiece` are intentionally omitted from dev deps — unit tests must run without them.

- [ ] **Step 5: Write minimal `README.md`**

```markdown
# FLUX Image Generator (Colab)

A small FastAPI service wrapping FLUX.1 [schnell] on a Colab L4 GPU, with a web UI at `/` and REST endpoints for txt2img / img2img.

## Run on Colab

```python
!pip install -r requirements.txt -q
!python run_colab.py
```

The script prints a TryCloudflare public URL and a Bearer token. Open the URL, paste the token when prompted.

## Run locally for development (no GPU)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```
```

- [ ] **Step 6: Write `tests/conftest.py` with shared fixtures**

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import pytest


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    return outputs


@pytest.fixture
def tmp_input_dir(tmp_path: Path) -> Path:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    return inputs
```

- [ ] **Step 7: Verify initial layout**

Run: `ls -la && cat requirements.txt`
Expected: all files exist, content matches above.

- [ ] **Step 8: Commit**

```bash
git add .gitignore README.md requirements.txt requirements-dev.txt app/__init__.py tests/__init__.py tests/conftest.py docs/
git commit -m "chore: project scaffolding and dev dependencies"
```

---

## Task 1: `app/config.py` — paths, defaults, token generation

**Files:**
- Create: `app/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
from __future__ import annotations

from pathlib import Path

from app import config


def test_token_is_url_safe_and_nontrivial():
    token = config.generate_token()
    assert isinstance(token, str)
    assert len(token) >= 32
    # url-safe alphabet: letters, digits, '-', '_'
    assert all(c.isalnum() or c in "-_" for c in token)


def test_tokens_are_unique():
    assert config.generate_token() != config.generate_token()


def test_defaults_have_expected_values():
    assert config.DEFAULT_WIDTH == 1024
    assert config.DEFAULT_HEIGHT == 1024
    assert config.DEFAULT_STEPS == 4
    assert config.DEFAULT_GUIDANCE_SCALE == 0.0
    assert config.DEFAULT_STRENGTH == 0.7
    assert config.MIN_SIZE == 256
    assert config.MAX_SIZE == 1536
    assert config.SIZE_MULTIPLE == 64
    assert config.MIN_STEPS == 1
    assert config.MAX_STEPS == 8
    assert config.MAX_INIT_IMAGE_BYTES == 10 * 1024 * 1024


def test_paths_are_pathlib():
    assert isinstance(config.OUTPUT_DIR, Path)
    assert isinstance(config.INPUT_DIR, Path)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_config.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.config'`).

- [ ] **Step 3: Implement `app/config.py`**

```python
# app/config.py
"""Shared constants, defaults, and token generation.

Nothing in this module imports torch / diffusers — safe to load anywhere.
"""

from __future__ import annotations

import secrets
from pathlib import Path

DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
DEFAULT_STEPS = 4
DEFAULT_GUIDANCE_SCALE = 0.0
DEFAULT_STRENGTH = 0.7

MIN_SIZE = 256
MAX_SIZE = 1536
SIZE_MULTIPLE = 64
MIN_STEPS = 1
MAX_STEPS = 8
MIN_STRENGTH = 0.0
MAX_STRENGTH = 1.0

MAX_PROMPT_LEN = 2000
MAX_INIT_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB after base64 decode

OUTPUT_DIR = Path("/content/outputs")
INPUT_DIR = Path("/content/inputs")

HISTORY_CAP = 50  # UI-side, informational


def generate_token() -> str:
    """Return a fresh URL-safe Bearer token."""
    return secrets.token_urlsafe(32)


def ensure_dirs() -> None:
    """Create OUTPUT_DIR and INPUT_DIR if missing. Safe to call repeatedly."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_config.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(config): paths, defaults, and random token generation"
```

---

## Task 2: `app/schemas.py` — Pydantic request/response models

**Files:**
- Create: `app/schemas.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_schemas.py
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
        # Craft a payload whose decoded size exceeds 10 MB
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_schemas.py -q`
Expected: FAIL (import error for `app.schemas`).

- [ ] **Step 3: Implement `app/schemas.py`**

```python
# app/schemas.py
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_schemas.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add app/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): request/response models with param validation"
```

---

## Task 3: `app/store.py` — TaskRecord and TaskStore

**Files:**
- Create: `app/store.py`
- Create: `tests/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_store.py
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.store import TaskRecord, TaskStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record(task_id: str, kind: str = "txt2img") -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        kind=kind,
        status="pending",
        params={"prompt": "x"},
        created_at=_now(),
        started_at=None,
        finished_at=None,
        result_path=None,
        error=None,
    )


@pytest.mark.asyncio
async def test_create_and_get():
    store = TaskStore()
    r = _record("a")
    await store.create(r)
    got = store.get("a")
    assert got is r


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    store = TaskStore()
    assert store.get("nope") is None


@pytest.mark.asyncio
async def test_set_status_updates_fields():
    store = TaskStore()
    await store.create(_record("a"))
    t = _now()
    await store.set_status("a", status="running", started_at=t)
    got = store.get("a")
    assert got.status == "running"
    assert got.started_at == t


@pytest.mark.asyncio
async def test_set_status_unknown_task_raises():
    store = TaskStore()
    with pytest.raises(KeyError):
        await store.set_status("nope", status="done")


@pytest.mark.asyncio
async def test_queue_position_counts_preceding_pending():
    store = TaskStore()
    for tid in ["a", "b", "c", "d"]:
        await store.create(_record(tid))
        await asyncio.sleep(0)  # ensure distinct timestamps
    # mark "b" running so it is no longer pending
    await store.set_status("b", status="running")
    assert store.queue_position("a") == 1
    assert store.queue_position("c") == 2  # a is ahead of c; b is running, not pending
    assert store.queue_position("d") == 3


@pytest.mark.asyncio
async def test_queue_position_none_when_not_pending():
    store = TaskStore()
    await store.create(_record("a"))
    await store.set_status("a", status="done")
    assert store.queue_position("a") is None


@pytest.mark.asyncio
async def test_queue_depth_counts_pending_and_running():
    store = TaskStore()
    await store.create(_record("a"))
    await store.create(_record("b"))
    await store.create(_record("c"))
    await store.set_status("a", status="running")
    await store.set_status("c", status="done")
    assert store.queue_depth() == 2  # a (running) + b (pending)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_store.py -q`
Expected: FAIL (import error).

- [ ] **Step 3: Implement `app/store.py`**

```python
# app/store.py
"""In-memory task store, guarded by an asyncio.Lock for writes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional


Status = Literal["pending", "running", "done", "failed"]
Kind = Literal["txt2img", "img2img"]


@dataclass
class TaskRecord:
    task_id: str
    kind: Kind
    status: Status
    params: dict[str, Any]
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result_path: Optional[str] = None
    error: Optional[str] = None


class TaskStore:
    """Dictionary-backed task store. Writes are serialized with an asyncio.Lock."""

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: TaskRecord) -> None:
        async with self._lock:
            self._records[record.task_id] = record

    def get(self, task_id: str) -> Optional[TaskRecord]:
        return self._records.get(task_id)

    async def set_status(self, task_id: str, **updates: Any) -> None:
        async with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise KeyError(task_id)
            for k, v in updates.items():
                if not hasattr(record, k):
                    raise AttributeError(f"TaskRecord has no field {k!r}")
                setattr(record, k, v)

    def queue_position(self, task_id: str) -> Optional[int]:
        """1-based position among pending tasks, ordered by created_at.

        Returns None if the task is not pending.
        """
        target = self._records.get(task_id)
        if target is None or target.status != "pending":
            return None
        ahead = sum(
            1
            for r in self._records.values()
            if r.status == "pending" and r.created_at <= target.created_at and r.task_id != target.task_id
        )
        return ahead + 1

    def queue_depth(self) -> int:
        """Count tasks that are pending or running (i.e., occupying the queue)."""
        return sum(1 for r in self._records.values() if r.status in ("pending", "running"))

    def all_records(self) -> list[TaskRecord]:
        return list(self._records.values())
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_store.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/store.py tests/test_store.py
git commit -m "feat(store): in-memory TaskStore with async-lock-guarded writes"
```

---

## Task 4: `app/auth.py` — Bearer token dependency

**Files:**
- Create: `app/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_auth.py
from __future__ import annotations

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app.auth import require_token, set_expected_token


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    def protected(_: None = Depends(require_token)):
        return {"ok": True}

    return app


def test_missing_header_returns_401():
    set_expected_token("secret")
    client = TestClient(_app())
    r = client.get("/protected")
    assert r.status_code == 401


def test_wrong_token_returns_401():
    set_expected_token("secret")
    client = TestClient(_app())
    r = client.get("/protected", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_malformed_header_returns_401():
    set_expected_token("secret")
    client = TestClient(_app())
    r = client.get("/protected", headers={"Authorization": "Basic nope"})
    assert r.status_code == 401


def test_correct_token_passes():
    set_expected_token("secret")
    client = TestClient(_app())
    r = client.get("/protected", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_auth.py -q`
Expected: FAIL (import error).

- [ ] **Step 3: Implement `app/auth.py`**

```python
# app/auth.py
"""Bearer-token dependency, with the expected token set once at startup."""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Header, HTTPException, status


_expected_token: Optional[str] = None


def set_expected_token(token: str) -> None:
    """Set the Bearer token the server expects. Call once at startup."""
    global _expected_token
    _expected_token = token


def require_token(authorization: Optional[str] = Header(default=None)) -> None:
    if _expected_token is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="server token not initialized",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    presented = authorization[len("Bearer "):].strip()
    if not hmac.compare_digest(presented, _expected_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_auth.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/test_auth.py
git commit -m "feat(auth): Bearer token FastAPI dependency"
```

---

## Task 5: `app/pipeline.py` — PipelineProtocol, FakePipeline, FluxPipelineHolder stub

This task defines the interface and a testable fake. The **real** `FluxPipelineHolder` body (torch/diffusers) comes in Task 13 and is verified manually on Colab.

**Files:**
- Create: `app/pipeline.py`
- Create: `tests/test_pipeline_fake.py`

- [ ] **Step 1: Write failing test for FakePipeline**

```python
# tests/test_pipeline_fake.py
from __future__ import annotations

from PIL import Image

from app.pipeline import FakePipeline


def test_fake_txt2img_returns_pil_image_of_requested_size():
    pipe = FakePipeline()
    img = pipe.generate(
        "txt2img",
        {"prompt": "x", "width": 512, "height": 512, "num_inference_steps": 4, "guidance_scale": 0.0, "seed": None},
    )
    assert isinstance(img, Image.Image)
    assert img.size == (512, 512)


def test_fake_img2img_returns_pil_image(tmp_path):
    init_path = tmp_path / "init.png"
    Image.new("RGB", (256, 256), color="blue").save(init_path, format="PNG")
    pipe = FakePipeline()
    img = pipe.generate(
        "img2img",
        {
            "prompt": "x",
            "init_image_path": str(init_path),
            "strength": 0.7,
            "num_inference_steps": 4,
            "guidance_scale": 0.0,
            "seed": None,
        },
    )
    assert isinstance(img, Image.Image)


def test_fake_is_loaded_true():
    pipe = FakePipeline()
    assert pipe.is_loaded() is True


def test_fake_can_simulate_oom():
    pipe = FakePipeline(raise_on_generate=RuntimeError("boom"))
    import pytest
    with pytest.raises(RuntimeError, match="boom"):
        pipe.generate("txt2img", {"prompt": "x", "width": 256, "height": 256,
                                   "num_inference_steps": 4, "guidance_scale": 0.0, "seed": None})
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_pipeline_fake.py -q`
Expected: FAIL (import error).

- [ ] **Step 3: Implement `app/pipeline.py` (fake + holder stub)**

```python
# app/pipeline.py
"""Pipeline protocol, a fake implementation for tests, and the real FLUX holder.

The FluxPipelineHolder body is filled in later (Task 13). At this stage it only
provides the same protocol so the rest of the app can be wired up and tested.
"""

from __future__ import annotations

from typing import Any, Protocol

from PIL import Image


class PipelineProtocol(Protocol):
    def is_loaded(self) -> bool: ...
    def load(self) -> None: ...
    def generate(self, kind: str, params: dict[str, Any]) -> Image.Image: ...


class FakePipeline:
    """In-memory stub pipeline, used by unit tests. GPU-free."""

    def __init__(self, raise_on_generate: BaseException | None = None) -> None:
        self._loaded = True
        self._raise = raise_on_generate

    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:  # pragma: no cover - already loaded
        self._loaded = True

    def generate(self, kind: str, params: dict[str, Any]) -> Image.Image:
        if self._raise is not None:
            raise self._raise
        if kind == "txt2img":
            w = int(params.get("width", 512))
            h = int(params.get("height", 512))
            return Image.new("RGB", (w, h), color=(128, 64, 200))
        if kind == "img2img":
            path = params["init_image_path"]
            with Image.open(path) as im:
                return im.convert("RGB").copy()
        raise ValueError(f"unknown kind: {kind}")


class FluxPipelineHolder:
    """Real FLUX.1-schnell pipeline holder. Body implemented in Task 13.

    Before Task 13 this class exists only to satisfy imports in main.py.
    Do NOT instantiate it in tests — use FakePipeline.
    """

    def __init__(self, model_id: str = "black-forest-labs/FLUX.1-schnell") -> None:
        self._model_id = model_id
        self._loaded = False
        self._txt2img = None
        self._img2img = None

    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        raise NotImplementedError("FluxPipelineHolder.load is implemented in Task 13")

    def generate(self, kind: str, params: dict[str, Any]) -> Image.Image:
        raise NotImplementedError("FluxPipelineHolder.generate is implemented in Task 13")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_pipeline_fake.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/pipeline.py tests/test_pipeline_fake.py
git commit -m "feat(pipeline): protocol, FakePipeline, FluxPipelineHolder stub"
```

---

## Task 6: `app/queue_worker.py` — worker loop

**Files:**
- Create: `app/queue_worker.py`
- Create: `tests/test_queue_worker.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_queue_worker.py
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.pipeline import FakePipeline
from app.queue_worker import Worker
from app.store import TaskRecord, TaskStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pending(task_id: str, kind: str = "txt2img", params: dict | None = None) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        kind=kind,
        status="pending",
        params=params or {"prompt": "x", "width": 256, "height": 256,
                          "num_inference_steps": 4, "guidance_scale": 0.0, "seed": None},
        created_at=_now(),
    )


@pytest.mark.asyncio
async def test_worker_processes_pending_task(tmp_output_dir: Path):
    store = TaskStore()
    queue: asyncio.Queue[str] = asyncio.Queue()
    pipe = FakePipeline()
    worker = Worker(store=store, queue=queue, pipeline=pipe, output_dir=tmp_output_dir)

    await store.create(_pending("a"))
    await queue.put("a")

    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(queue.join(), timeout=2.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    rec = store.get("a")
    assert rec.status == "done"
    assert rec.started_at is not None
    assert rec.finished_at is not None
    assert rec.result_path == str(tmp_output_dir / "a.png")
    assert Path(rec.result_path).exists()


@pytest.mark.asyncio
async def test_worker_marks_failure_and_continues(tmp_output_dir: Path):
    store = TaskStore()
    queue: asyncio.Queue[str] = asyncio.Queue()
    # First task raises, second succeeds
    calls = {"n": 0}

    class FlakyPipeline(FakePipeline):
        def generate(self, kind, params):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return super().generate(kind, params)

    worker = Worker(store=store, queue=queue, pipeline=FlakyPipeline(), output_dir=tmp_output_dir)

    await store.create(_pending("a"))
    await store.create(_pending("b"))
    await queue.put("a")
    await queue.put("b")

    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(queue.join(), timeout=2.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert store.get("a").status == "failed"
    assert "RuntimeError" in store.get("a").error
    assert store.get("b").status == "done"


@pytest.mark.asyncio
async def test_worker_is_serial(tmp_output_dir: Path):
    """Two tasks in flight at the same time should never be observed."""
    store = TaskStore()
    queue: asyncio.Queue[str] = asyncio.Queue()
    running_overlap = {"max": 0, "current": 0}

    class SlowPipeline(FakePipeline):
        def generate(self, kind, params):
            running_overlap["current"] += 1
            running_overlap["max"] = max(running_overlap["max"], running_overlap["current"])
            # brief synchronous work — the worker runs generate inside to_thread
            import time
            time.sleep(0.05)
            running_overlap["current"] -= 1
            return super().generate(kind, params)

    worker = Worker(store=store, queue=queue, pipeline=SlowPipeline(), output_dir=tmp_output_dir)

    for tid in ["a", "b", "c"]:
        await store.create(_pending(tid))
        await queue.put(tid)

    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(queue.join(), timeout=3.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert running_overlap["max"] == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_queue_worker.py -q`
Expected: FAIL (import error).

- [ ] **Step 3: Implement `app/queue_worker.py`**

```python
# app/queue_worker.py
"""Single async worker consuming task IDs from an asyncio.Queue."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.pipeline import PipelineProtocol
from app.store import TaskStore

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Worker:
    def __init__(
        self,
        store: TaskStore,
        queue: asyncio.Queue[str],
        pipeline: PipelineProtocol,
        output_dir: Path,
    ) -> None:
        self.store = store
        self.queue = queue
        self.pipeline = pipeline
        self.output_dir = output_dir

    async def run(self) -> None:
        """Process tasks until cancelled. Never crashes on task failure."""
        while True:
            task_id = await self.queue.get()
            try:
                await self._process(task_id)
            finally:
                self.queue.task_done()

    async def _process(self, task_id: str) -> None:
        record = self.store.get(task_id)
        if record is None:
            logger.warning("task %s not found in store, skipping", task_id)
            return

        await self.store.set_status(task_id, status="running", started_at=_now())
        try:
            image = await asyncio.to_thread(
                self.pipeline.generate, record.kind, record.params
            )
            out_path = self.output_dir / f"{task_id}.png"
            await asyncio.to_thread(image.save, str(out_path), "PNG")
            await self.store.set_status(
                task_id,
                status="done",
                finished_at=_now(),
                result_path=str(out_path),
            )
        except Exception as e:
            logger.error("task %s failed:\n%s", task_id, traceback.format_exc())
            await self.store.set_status(
                task_id,
                status="failed",
                finished_at=_now(),
                error=f"{type(e).__name__}: {str(e)[:500]}",
            )
            # Best-effort GPU cache clear without importing torch at module level.
            _try_empty_cuda_cache()


def _try_empty_cuda_cache() -> None:
    try:
        import torch  # imported lazily — not required in tests

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_queue_worker.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/queue_worker.py tests/test_queue_worker.py
git commit -m "feat(worker): serial async worker with task-level error isolation"
```

---

## Task 7: `app/routes.py` — `/healthz` + route wiring helper

**Files:**
- Create: `app/routes.py`
- Create: `tests/test_routes.py` (we extend it in later tasks)

- [ ] **Step 1: Write failing test for `/healthz`**

```python
# tests/test_routes.py
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
```

Note: TestClient's context manager drives FastAPI's lifespan, which starts the worker task on the same anyio-backed event loop that serves requests. This keeps the `asyncio.Queue` and `asyncio.Lock` bound to one loop. Fixture yields `(client, store, queue, output_dir)`; downstream tests unpack the shape they need.

- [ ] **Step 2: Run the test to verify failure**

Run: `pytest tests/test_routes.py::test_healthz_does_not_require_auth -q`
Expected: FAIL (import error).

- [ ] **Step 3: Implement `app/routes.py` with `register_routes` and `/healthz`**

```python
# app/routes.py
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
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_routes.py::test_healthz_does_not_require_auth -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes.py tests/test_routes.py
git commit -m "feat(routes): register_routes plumbing and /healthz"
```

---

## Task 8: `POST /tasks/txt2img`

**Files:**
- Modify: `app/routes.py`
- Modify: `tests/test_routes.py` (append tests)

- [ ] **Step 1: Add failing test to `tests/test_routes.py`**

Append to `tests/test_routes.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_routes.py -q`
Expected: new tests FAIL (`/tasks/txt2img` does not exist).

- [ ] **Step 3: Extend `app/routes.py` with the txt2img endpoint**

Inside `register_routes`, after `/healthz`, add:

```python
    from datetime import datetime, timezone
    from uuid import uuid4
    from fastapi import Depends, HTTPException, status as http_status

    from app.auth import require_token
    from app.schemas import TaskSubmitResponse, TxtToImgRequest
    from app.store import TaskRecord

    def _now():
        return datetime.now(timezone.utc)

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
```

Also add a placeholder `GET /tasks/{id}` so the polling in tests doesn't 404 (implemented fully in Task 10):

```python
    @app.get("/tasks/{task_id}", dependencies=[Depends(require_token)])
    async def _get_task_placeholder(task_id: str):
        rec = store.get(task_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="not found")
        payload = {
            "task_id": rec.task_id,
            "kind": rec.kind,
            "status": rec.status,
            "created_at": rec.created_at.isoformat(),
            "started_at": rec.started_at.isoformat() if rec.started_at else None,
            "finished_at": rec.finished_at.isoformat() if rec.finished_at else None,
            "queue_position": store.queue_position(task_id),
            "image_url": f"/tasks/{rec.task_id}/image" if rec.status == "done" else None,
            "error": rec.error,
        }
        return payload
```

(The placeholder will be replaced by a fully Pydantic-typed version in Task 10.)

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_routes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes.py tests/test_routes.py
git commit -m "feat(routes): POST /tasks/txt2img submission + polling placeholder"
```

---

## Task 9: `POST /tasks/img2img`

**Files:**
- Modify: `app/routes.py`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_routes.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_routes.py -q`
Expected: new tests FAIL.

- [ ] **Step 3: Extend `app/routes.py` with the img2img endpoint**

Inside `register_routes`, add:

```python
    import base64 as _b64
    from app.schemas import ImgToImgRequest

    @app.post(
        "/tasks/img2img",
        response_model=TaskSubmitResponse,
        status_code=http_status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_token)],
    )
    async def submit_img2img(req: ImgToImgRequest) -> TaskSubmitResponse:
        task_id = uuid4().hex
        raw = _b64.b64decode(req.init_image, validate=True)
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_routes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes.py tests/test_routes.py
git commit -m "feat(routes): POST /tasks/img2img saves init image and queues task"
```

---

## Task 10: Replace `GET /tasks/{id}` placeholder with Pydantic-typed handler

**Files:**
- Modify: `app/routes.py`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Add failing assertion**

Append to `tests/test_routes.py`:

```python
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
```

- [ ] **Step 2: Run test to confirm current placeholder passes but is untyped**

Run: `pytest tests/test_routes.py::test_status_response_has_expected_fields_when_pending tests/test_routes.py::test_status_404_for_unknown -q`
Expected: These may already pass since the placeholder returns the same keys. If they pass, proceed to tighten the implementation anyway for consistency.

- [ ] **Step 3: Replace the placeholder with a Pydantic-typed handler**

In `app/routes.py`, remove the `_get_task_placeholder` function and add:

```python
    from app.schemas import TaskStatusResponse

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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_routes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes.py tests/test_routes.py
git commit -m "feat(routes): typed GET /tasks/{id} status response"
```

---

## Task 11: `GET /tasks/{id}/image`

**Files:**
- Modify: `app/routes.py`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_routes.py`:

```python
def test_image_download_requires_auth(test_app):
    client, _, _, _ = test_app
    r = client.post("/tasks/txt2img", json={"prompt": "x", "width": 256, "height": 256}, headers=AUTH)
    tid = r.json()["task_id"]
    _wait_for_status(client, tid, {"done"})
    r = client.get(f"/tasks/{tid}/image")
    assert r.status_code == 401


def test_image_download_returns_png_when_done(test_app):
    client, _, _, _ = test_app
    r = client.post("/tasks/txt2img", json={"prompt": "x", "width": 256, "height": 256}, headers=AUTH)
    tid = r.json()["task_id"]
    _wait_for_status(client, tid, {"done"})
    r = client.get(f"/tasks/{tid}/image", headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_404_for_unknown(test_app):
    client, _, _, _ = test_app
    r = client.get("/tasks/nope/image", headers=AUTH)
    assert r.status_code == 404


def test_image_409_when_not_done(test_app, monkeypatch):
    client, store, _, _ = test_app
    # Submit a task and immediately query before it completes by forcing
    # status back to pending. (Race-free way: flip status after submit.)
    r = client.post("/tasks/txt2img", json={"prompt": "x", "width": 256, "height": 256}, headers=AUTH)
    tid = r.json()["task_id"]
    # Best-effort: set status to pending synchronously on the in-memory record
    rec = store.get(tid)
    rec.status = "pending"
    rec.result_path = None
    r = client.get(f"/tasks/{tid}/image", headers=AUTH)
    assert r.status_code == 409
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_routes.py -q`
Expected: new tests FAIL (endpoint missing).

- [ ] **Step 3: Add the image endpoint to `app/routes.py`**

Inside `register_routes`:

```python
    from fastapi.responses import FileResponse

    @app.get("/tasks/{task_id}/image", dependencies=[Depends(require_token)])
    async def download_image(task_id: str):
        rec = store.get(task_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="not found")
        if rec.status != "done" or not rec.result_path:
            raise HTTPException(status_code=409, detail=f"task status is {rec.status}")
        return FileResponse(rec.result_path, media_type="image/png", filename=f"{task_id}.png")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_routes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes.py tests/test_routes.py
git commit -m "feat(routes): GET /tasks/{id}/image returns PNG when done"
```

---

## Task 12: `app/main.py` — FastAPI app + lifespan

**Files:**
- Create: `app/main.py`

No new unit tests for `main.py` itself — coverage comes from the route tests. We smoke-test that the real module imports cleanly and `create_app()` returns a FastAPI instance.

- [ ] **Step 1: Add a smoke test**

Append to `tests/test_routes.py`:

```python
def test_create_app_smoke():
    from app.main import create_app

    app = create_app(use_fake_pipeline=True, token="smoke", output_dir=None, input_dir=None)
    assert app is not None
    client = TestClient(app)
    # lifespan is triggered on client context enter
    with client:
        r = client.get("/healthz")
        assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_routes.py::test_create_app_smoke -q`
Expected: FAIL (`app.main` not importable).

- [ ] **Step 3: Implement `app/main.py`**

```python
# app/main.py
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


# For `uvicorn app.main:app`
app = create_app()
```

- [ ] **Step 4: Run all tests**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_routes.py
git commit -m "feat(main): application factory and lifespan wiring"
```

---

## Task 13: Real `FluxPipelineHolder` implementation (Colab-only verification)

**Files:**
- Modify: `app/pipeline.py`

**No automated test** — the real pipeline requires a CUDA GPU. We verify manually on Colab in Task 19.

- [ ] **Step 1: Replace `FluxPipelineHolder` body**

In `app/pipeline.py`, replace the existing `FluxPipelineHolder` class with:

```python
class FluxPipelineHolder:
    """FLUX.1 [schnell] pipeline holder. Loads txt2img and img2img pipelines
    sharing model weights. Only safe to call on a machine with CUDA.
    """

    def __init__(self, model_id: str = "black-forest-labs/FLUX.1-schnell") -> None:
        self._model_id = model_id
        self._loaded = False
        self._txt2img = None
        self._img2img = None

    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        import torch
        from diffusers import FluxPipeline, FluxImg2ImgPipeline

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU required for FluxPipelineHolder")

        dtype = torch.bfloat16
        self._txt2img = FluxPipeline.from_pretrained(self._model_id, torch_dtype=dtype)
        self._txt2img.to("cuda")
        try:
            self._txt2img.vae.enable_tiling()
        except Exception:
            pass

        # img2img pipeline reuses the same model weights
        self._img2img = FluxImg2ImgPipeline(
            vae=self._txt2img.vae,
            text_encoder=self._txt2img.text_encoder,
            text_encoder_2=self._txt2img.text_encoder_2,
            tokenizer=self._txt2img.tokenizer,
            tokenizer_2=self._txt2img.tokenizer_2,
            transformer=self._txt2img.transformer,
            scheduler=self._txt2img.scheduler,
        )

        self._loaded = True

    def generate(self, kind: str, params: dict):
        import torch
        from PIL import Image

        if not self._loaded:
            raise RuntimeError("pipeline not loaded")

        seed = params.get("seed")
        generator = None
        if seed is not None:
            generator = torch.Generator(device="cuda").manual_seed(int(seed))

        if kind == "txt2img":
            result = self._txt2img(
                prompt=params["prompt"],
                width=int(params["width"]),
                height=int(params["height"]),
                num_inference_steps=int(params["num_inference_steps"]),
                guidance_scale=float(params["guidance_scale"]),
                generator=generator,
            )
            return result.images[0]

        if kind == "img2img":
            init = Image.open(params["init_image_path"]).convert("RGB")
            result = self._img2img(
                prompt=params["prompt"],
                image=init,
                strength=float(params["strength"]),
                num_inference_steps=int(params["num_inference_steps"]),
                guidance_scale=float(params["guidance_scale"]),
                generator=generator,
            )
            return result.images[0]

        raise ValueError(f"unknown kind: {kind}")
```

- [ ] **Step 2: Confirm unit tests still pass (FakePipeline unchanged)**

Run: `pytest -q`
Expected: all pass (nothing imports the real holder's body during tests).

- [ ] **Step 3: Commit**

```bash
git add app/pipeline.py
git commit -m "feat(pipeline): real FLUX.1 [schnell] txt2img + img2img holder"
```

---

## Task 14: Static UI — scaffold + token modal + layout

**Files:**
- Create: `app/static/index.html`
- Modify: `app/routes.py` (add `GET /`)
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Add failing test for `GET /`**

Append to `tests/test_routes.py`:

```python
def test_root_serves_html_without_auth(test_app):
    client, _, _, _ = test_app
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title>FLUX Image Generator</title>" in r.text
    assert "localStorage" in r.text  # token handling lives in JS
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_routes.py::test_root_serves_html_without_auth -q`
Expected: FAIL.

- [ ] **Step 3: Create `app/static/index.html` with layout + token modal**

Create `app/static/index.html` containing the initial shell. The full single-file UI is built up across Tasks 14-17; here we write the entire scaffold with empty handlers so the flow tests in later tasks can fill them in.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>FLUX Image Generator</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { margin: 0; display: grid; grid-template-columns: 240px 1fr; height: 100vh; }
    header { grid-column: 1 / -1; display: flex; justify-content: space-between;
             align-items: center; padding: 0.6rem 1rem; border-bottom: 1px solid #8884; }
    #history-pane { border-right: 1px solid #8884; overflow-y: auto; padding: 0.5rem; }
    #history-pane h3 { margin: 0 0 0.5rem 0; font-size: 0.9rem; }
    .thumb { width: 96px; height: 96px; object-fit: cover; cursor: pointer; margin: 2px;
             border: 1px solid #8884; border-radius: 4px; }
    main { padding: 1rem; overflow-y: auto; }
    .mode-toggle button { padding: 0.4rem 0.8rem; }
    .mode-toggle button.active { background: #456; color: white; }
    form label { display: block; margin: 0.5rem 0 0.2rem 0; font-size: 0.85rem; }
    form input, form textarea { width: 100%; box-sizing: border-box; padding: 0.3rem; }
    form .row { display: flex; gap: 0.5rem; }
    form .row > div { flex: 1; }
    #result { margin-top: 1rem; }
    #result img { max-width: 100%; border: 1px solid #8884; border-radius: 4px; }
    #status-line { font-size: 0.9rem; color: #888; margin-top: 0.5rem; }
    .modal-backdrop { position: fixed; inset: 0; background: #0008;
                      display: flex; align-items: center; justify-content: center; }
    .modal { background: white; color: black; padding: 1rem 1.5rem; border-radius: 6px;
             width: 400px; max-width: 90vw; }
    .hidden { display: none !important; }
    body { color: inherit; background: inherit; }
    @media (prefers-color-scheme: dark) { .modal { background: #222; color: #eee; } }
  </style>
</head>
<body>
  <header>
    <strong>FLUX Image Generator</strong>
    <div>
      <span id="token-indicator">token: not set</span>
      <button id="clear-token-btn" type="button">clear token</button>
    </div>
  </header>

  <aside id="history-pane">
    <h3>History <button id="clear-history-btn" type="button" style="font-size:0.7rem;float:right;">clear</button></h3>
    <div id="history-list"></div>
  </aside>

  <main>
    <div class="mode-toggle">
      <button type="button" data-mode="txt2img" class="active">txt2img</button>
      <button type="button" data-mode="img2img">img2img</button>
    </div>

    <form id="gen-form">
      <label>Prompt
        <textarea name="prompt" rows="3" required></textarea>
      </label>

      <div class="row">
        <div><label>Width<input name="width" type="number" value="1024" step="64" min="256" max="1536" /></label></div>
        <div><label>Height<input name="height" type="number" value="1024" step="64" min="256" max="1536" /></label></div>
        <div><label>Steps<input name="num_inference_steps" type="number" value="4" min="1" max="8" /></label></div>
        <div><label>Seed<input name="seed" type="number" placeholder="random" /></label></div>
      </div>

      <div id="img2img-fields" class="hidden">
        <label>Init image <input name="init_image_file" type="file" accept="image/png,image/jpeg" /></label>
        <label>Strength <input name="strength" type="number" value="0.7" step="0.05" min="0" max="1" /></label>
      </div>

      <button id="generate-btn" type="submit">Generate</button>
    </form>

    <div id="result">
      <div id="status-line"></div>
      <img id="result-image" class="hidden" alt="generated image" />
      <div id="result-actions" class="hidden">
        <a id="download-link" download>Download</a>
        <button id="rerun-btn" type="button">Re-run with same params</button>
      </div>
    </div>
  </main>

  <div id="token-modal" class="modal-backdrop hidden">
    <div class="modal">
      <h3>Enter API token</h3>
      <p>The token is printed in the Colab log at startup.</p>
      <input id="token-input" type="password" style="width:100%;" />
      <div style="margin-top:0.5rem;display:flex;gap:0.5rem;justify-content:flex-end;">
        <button id="token-save" type="button">Save</button>
      </div>
    </div>
  </div>

  <script>
  // -----------------------------------------------------------------------
  // Token management
  // -----------------------------------------------------------------------
  const TOKEN_KEY = "flux_token";
  const HISTORY_KEY = "flux_history";
  const HISTORY_CAP = 50;

  function getToken()       { return localStorage.getItem(TOKEN_KEY) || ""; }
  function setToken(t)      { localStorage.setItem(TOKEN_KEY, t); updateTokenIndicator(); }
  function clearToken()     { localStorage.removeItem(TOKEN_KEY); updateTokenIndicator(); showTokenModal(); }
  function updateTokenIndicator() {
    document.getElementById("token-indicator").textContent =
      getToken() ? "token: set ✓" : "token: not set";
  }
  function showTokenModal() { document.getElementById("token-modal").classList.remove("hidden"); }
  function hideTokenModal() { document.getElementById("token-modal").classList.add("hidden"); }

  document.getElementById("token-save").addEventListener("click", () => {
    const v = document.getElementById("token-input").value.trim();
    if (v) { setToken(v); hideTokenModal(); }
  });
  document.getElementById("clear-token-btn").addEventListener("click", clearToken);

  if (!getToken()) showTokenModal();
  updateTokenIndicator();

  // Submit/history handlers are attached in Tasks 15-17.
  window.__flux = { getToken, setToken, clearToken, HISTORY_KEY, HISTORY_CAP };
  </script>
</body>
</html>
```

- [ ] **Step 4: Serve the file from `GET /` in `app/routes.py`**

Inside `register_routes`, add near the top:

```python
    from fastapi.responses import FileResponse as _FR
    _static_dir = Path(__file__).parent / "static"

    @app.get("/", include_in_schema=False)
    def index():
        return _FR(_static_dir / "index.html", media_type="text/html")
```

- [ ] **Step 5: Run test to verify pass**

Run: `pytest tests/test_routes.py::test_root_serves_html_without_auth -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/static/index.html app/routes.py tests/test_routes.py
git commit -m "feat(ui): static UI scaffold + token modal + GET / route"
```

---

## Task 15: UI — txt2img submit & poll & display

**Files:**
- Modify: `app/static/index.html` (append inside `<script>` block before the closing `</script>`)

This task has no automated test — we rely on a manual verification step. The logic is small and self-contained so this is acceptable.

- [ ] **Step 1: Extend the script in `index.html`**

Inside `<script>...</script>`, replace the line
`window.__flux = { getToken, setToken, clearToken, HISTORY_KEY, HISTORY_CAP };`
with the following block (followed by that same `window.__flux = ...` line at the end):

```js
  // -----------------------------------------------------------------------
  // Mode toggle
  // -----------------------------------------------------------------------
  let mode = "txt2img";
  document.querySelectorAll(".mode-toggle button").forEach(btn => {
    btn.addEventListener("click", () => {
      mode = btn.dataset.mode;
      document.querySelectorAll(".mode-toggle button").forEach(b =>
        b.classList.toggle("active", b === btn));
      document.getElementById("img2img-fields").classList.toggle("hidden", mode !== "img2img");
    });
  });

  // -----------------------------------------------------------------------
  // API helpers
  // -----------------------------------------------------------------------
  async function apiPost(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer " + getToken() },
      body: JSON.stringify(body),
    });
    if (res.status === 401) { clearToken(); throw new Error("unauthorized"); }
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }
  async function apiGet(path) {
    const res = await fetch(path, { headers: { "Authorization": "Bearer " + getToken() } });
    if (res.status === 401) { clearToken(); throw new Error("unauthorized"); }
    return res;
  }

  // -----------------------------------------------------------------------
  // Submit form
  // -----------------------------------------------------------------------
  const form = document.getElementById("gen-form");
  const statusLine = document.getElementById("status-line");
  const resultImg = document.getElementById("result-image");
  const resultActions = document.getElementById("result-actions");
  const downloadLink = document.getElementById("download-link");

  function formValues() {
    const fd = new FormData(form);
    const v = {
      prompt: fd.get("prompt"),
      width: parseInt(fd.get("width"), 10),
      height: parseInt(fd.get("height"), 10),
      num_inference_steps: parseInt(fd.get("num_inference_steps"), 10),
    };
    const seed = fd.get("seed");
    if (seed !== null && seed !== "") v.seed = parseInt(seed, 10);
    if (mode === "img2img") {
      v.strength = parseFloat(fd.get("strength"));
    }
    return v;
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const s = r.result;
        const idx = s.indexOf(",");
        resolve(idx >= 0 ? s.slice(idx + 1) : s);
      };
      r.onerror = reject;
      r.readAsDataURL(file);
    });
  }

  async function pollUntilDone(taskId) {
    while (true) {
      const r = await apiGet(`/tasks/${taskId}`);
      if (!r.ok) throw new Error(`status ${r.status}`);
      const body = await r.json();
      if (body.status === "done") return body;
      if (body.status === "failed") throw new Error(body.error || "task failed");
      const pos = body.queue_position ? `(queue pos ${body.queue_position})` : "";
      statusLine.textContent = `status: ${body.status} ${pos}`;
      await new Promise(r => setTimeout(r, 1000));
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!getToken()) { showTokenModal(); return; }
    resultImg.classList.add("hidden");
    resultActions.classList.add("hidden");
    statusLine.textContent = "submitting...";

    try {
      let body = formValues();
      let path = "/tasks/txt2img";
      let initThumbDataUrl = null;
      if (mode === "img2img") {
        const file = form.elements["init_image_file"].files[0];
        if (!file) throw new Error("select an image file");
        body.init_image = await fileToBase64(file);
        path = "/tasks/img2img";
      }
      const submitted = await apiPost(path, body);
      const done = await pollUntilDone(submitted.task_id);

      const imgRes = await apiGet(done.image_url);
      const blob = await imgRes.blob();
      const url = URL.createObjectURL(blob);
      resultImg.src = url;
      resultImg.classList.remove("hidden");
      downloadLink.href = url;
      downloadLink.download = `${submitted.task_id}.png`;
      resultActions.classList.remove("hidden");
      statusLine.textContent = "done";

      // History hook — added in Task 17
      if (window.__fluxAddHistory) {
        await window.__fluxAddHistory({
          task_id: submitted.task_id,
          kind: mode,
          prompt: body.prompt,
          params: body,
          blob,
          created_at: new Date().toISOString(),
        });
      }
    } catch (err) {
      statusLine.textContent = "error: " + err.message;
    }
  });

  document.getElementById("rerun-btn").addEventListener("click", () => {
    form.requestSubmit();
  });
```

- [ ] **Step 2: Manual verification plan**

Since UI behavior is not automatically tested, the validator (Task 19) executes this checklist on Colab:
1. Open the TryCloudflare URL, see the token modal
2. Paste the token from Colab logs, modal closes, indicator shows "token: set ✓"
3. Type a prompt, click Generate, see "status: pending", then "status: running", then result image
4. Click Download, PNG saves locally
5. Switch to img2img, pick a file, submit, see result

- [ ] **Step 3: Confirm backend tests still pass**

Run: `pytest -q`
Expected: PASS (no backend change).

- [ ] **Step 4: Commit**

```bash
git add app/static/index.html
git commit -m "feat(ui): txt2img/img2img submit, poll, and display result"
```

---

## Task 16: UI — img2img flow validation (no new code beyond Task 15)

Task 15 already wired img2img submission. This task exists purely to document the manual checklist and to separate the commit boundary should Task 15 need iteration. **Skip if you already verified img2img in Task 15.**

- [ ] **Step 1: Manual checklist on Colab**

1. Switch to img2img mode
2. Select a small PNG/JPEG (~1 MB)
3. Set strength to 0.5
4. Submit — confirm server logs show `POST /tasks/img2img 202`
5. Result image appears, visibly derived from the init image

- [ ] **Step 2: No commit (no code change)**

---

## Task 17: UI — localStorage history sidebar

**Files:**
- Modify: `app/static/index.html`

- [ ] **Step 1: Extend the script**

Before the final `window.__flux = {...}` line, append:

```js
  // -----------------------------------------------------------------------
  // History (localStorage)
  // -----------------------------------------------------------------------
  function readHistory() {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); }
    catch { return []; }
  }
  function writeHistory(arr) {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(arr));
    } catch (e) {
      // QuotaExceededError: drop oldest until it fits
      while (arr.length > 1) {
        arr.pop();
        try { localStorage.setItem(HISTORY_KEY, JSON.stringify(arr)); return; }
        catch { /* keep shrinking */ }
      }
    }
  }

  async function makeThumbnail(blob, maxEdge = 256, quality = 0.7) {
    const url = URL.createObjectURL(blob);
    try {
      const img = await new Promise((resolve, reject) => {
        const i = new Image();
        i.onload = () => resolve(i);
        i.onerror = reject;
        i.src = url;
      });
      const ratio = Math.min(1, maxEdge / Math.max(img.width, img.height));
      const w = Math.round(img.width * ratio);
      const h = Math.round(img.height * ratio);
      const canvas = document.createElement("canvas");
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(img, 0, 0, w, h);
      return canvas.toDataURL("image/jpeg", quality);
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  window.__fluxAddHistory = async function (entry) {
    const { blob, ...meta } = entry;
    const thumbnail = await makeThumbnail(blob);
    // Do NOT store init_image base64 in history — too large.
    if (meta.params && meta.params.init_image) delete meta.params.init_image;
    const stored = { ...meta, thumbnail };
    const arr = readHistory();
    arr.unshift(stored);
    while (arr.length > HISTORY_CAP) arr.pop();
    writeHistory(arr);
    renderHistory();
  };

  function renderHistory() {
    const list = document.getElementById("history-list");
    list.innerHTML = "";
    for (const entry of readHistory()) {
      const img = document.createElement("img");
      img.className = "thumb";
      img.src = entry.thumbnail;
      img.title = `${entry.kind}: ${entry.prompt}`;
      img.addEventListener("click", () => showHistoryEntry(entry));
      list.appendChild(img);
    }
  }

  async function showHistoryEntry(entry) {
    // Re-populate form
    form.elements["prompt"].value = entry.prompt || "";
    if (entry.params) {
      for (const key of ["width", "height", "num_inference_steps", "seed", "strength"]) {
        if (entry.params[key] !== undefined && form.elements[key]) {
          form.elements[key].value = entry.params[key];
        }
      }
    }
    // Switch mode button to match
    document.querySelectorAll(".mode-toggle button").forEach(b =>
      b.classList.toggle("active", b.dataset.mode === entry.kind));
    mode = entry.kind;
    document.getElementById("img2img-fields").classList.toggle("hidden", mode !== "img2img");

    // Try to fetch full image; fall back to thumbnail
    statusLine.textContent = "loading...";
    try {
      const r = await apiGet(`/tasks/${entry.task_id}/image`);
      if (r.ok) {
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        resultImg.src = url;
        downloadLink.href = url;
        downloadLink.download = `${entry.task_id}.png`;
        statusLine.textContent = "restored from server";
      } else {
        resultImg.src = entry.thumbnail;
        downloadLink.removeAttribute("href");
        statusLine.textContent = "full image no longer available (thumbnail only)";
      }
    } catch (e) {
      resultImg.src = entry.thumbnail;
      statusLine.textContent = "full image no longer available (thumbnail only)";
    }
    resultImg.classList.remove("hidden");
    resultActions.classList.remove("hidden");
  }

  document.getElementById("clear-history-btn").addEventListener("click", () => {
    if (confirm("Clear all local history?")) {
      localStorage.removeItem(HISTORY_KEY);
      renderHistory();
    }
  });

  renderHistory();
```

- [ ] **Step 2: Manual verification checklist**

1. Generate 2–3 images, confirm thumbnails appear in sidebar
2. Refresh the page → history still there
3. Click a thumbnail → form pre-fills with the stored params; image displays
4. Click "clear" → history empties

- [ ] **Step 3: Commit**

```bash
git add app/static/index.html
git commit -m "feat(ui): localStorage history with thumbnails and click-to-restore"
```

---

## Task 18: `run_colab.py` — entry script (token + cloudflared + uvicorn)

**Files:**
- Create: `run_colab.py`

- [ ] **Step 1: Implement `run_colab.py`**

```python
# run_colab.py
"""Colab entry point.

1. Generate a random Bearer token and print it.
2. Download cloudflared if not present.
3. Launch `cloudflared tunnel --url http://localhost:8000` as a subprocess,
   scrape its output for the *.trycloudflare.com URL, and print it.
4. Run uvicorn serving app.main:app.

If cloudflared exits unexpectedly, this script exits non-zero.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from app import config

CLOUDFLARED_URLS = {
    "Linux-x86_64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "Linux-aarch64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    "Darwin-x86_64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
    "Darwin-arm64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
}

BIN_DIR = Path("/content/bin") if Path("/content").exists() else Path.cwd() / "bin"


def ensure_cloudflared() -> Path:
    existing = shutil.which("cloudflared")
    if existing:
        return Path(existing)

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target = BIN_DIR / "cloudflared"
    if target.exists():
        return target

    key = f"{platform.system()}-{platform.machine()}"
    url = CLOUDFLARED_URLS.get(key)
    if not url:
        raise RuntimeError(f"no cloudflared download configured for {key}")

    print(f"[run_colab] downloading cloudflared for {key} ...", flush=True)
    urllib.request.urlretrieve(url, target)
    target.chmod(0o755)
    return target


TUNNEL_URL_RE = re.compile(r"https://[A-Za-z0-9\-]+\.trycloudflare\.com")


def start_tunnel(bin_path: Path, port: int) -> tuple[subprocess.Popen, str]:
    proc = subprocess.Popen(
        [str(bin_path), "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    found_url: list[str] = []

    def _reader() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            sys.stdout.write(f"[cloudflared] {line}")
            sys.stdout.flush()
            if not found_url:
                m = TUNNEL_URL_RE.search(line)
                if m:
                    found_url.append(m.group(0))

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    deadline = time.time() + 30
    while time.time() < deadline and not found_url:
        if proc.poll() is not None:
            raise RuntimeError("cloudflared exited before publishing a URL")
        time.sleep(0.2)
    if not found_url:
        proc.terminate()
        raise RuntimeError("timed out waiting for cloudflared URL")
    return proc, found_url[0]


def main() -> int:
    port = int(os.environ.get("FLUX_PORT", "8000"))
    token = os.environ.get("FLUX_TOKEN") or config.generate_token()
    os.environ["FLUX_TOKEN"] = token

    bin_path = ensure_cloudflared()
    tunnel_proc, public_url = start_tunnel(bin_path, port)

    print("=" * 70, flush=True)
    print(f"FLUX Image Generator is publishing on: {public_url}", flush=True)
    print(f"Bearer token:                          {token}", flush=True)
    print("=" * 70, flush=True)

    import uvicorn

    def _handle_sig(_signum, _frame):
        tunnel_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    try:
        uvicorn.run("app.main:app", host="0.0.0.0", port=port)
    finally:
        if tunnel_proc.poll() is None:
            tunnel_proc.terminate()
            try:
                tunnel_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel_proc.kill()

    if tunnel_proc.returncode not in (0, -signal.SIGTERM):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run backend unit tests unchanged**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add run_colab.py
git commit -m "feat(entry): run_colab.py with cloudflared tunnel and uvicorn"
```

---

## Task 19: Colab end-to-end manual verification

**Files:** none (README update)

This task has no code; it runs the whole system on Colab Pro L4 and confirms each success criterion from the spec.

- [ ] **Step 1: Push branch to GitHub / copy files to Colab**

Using whichever transport the user prefers. If the user uses a GitHub repo:

```bash
git remote add origin <repo-url>
git push -u origin main
```

Then in Colab:
```python
!git clone <repo-url>
%cd llm-image-generator
!pip install -r requirements.txt -q
!python run_colab.py
```

- [ ] **Step 2: Verify each success criterion**

From the spec's "Success criteria" section:
- [ ] `POST /tasks/txt2img` returns `202` within <50 ms (measure with `curl -w '%{time_total}'`)
- [ ] A 1024×1024 txt2img completes in ≤10 s end-to-end
- [ ] Worker survives a deliberately-OOMing request (try 1536×1536, steps=8) — subsequent task still works
- [ ] 1 Hz polling for 30 s does not get rate-limited by the tunnel
- [ ] Wrong Bearer token returns 401
- [ ] `GET /` loads the UI without auth
- [ ] Token modal appears on first visit; `localStorage.flux_token` is set after save
- [ ] txt2img from UI yields an image within ~10 s of clicking Generate
- [ ] Refreshing the page preserves history sidebar
- [ ] Clicking a history thumbnail re-populates the form and shows the image

- [ ] **Step 3: Record results in README**

Append to `README.md`:

```markdown
## Verified on Colab Pro L4 (2026-04-18)

- 1024×1024 txt2img: ~3.8 s pipeline, ~4.1 s end-to-end
- 1536×1536 txt2img steps=8: OOM recovered, subsequent tasks succeed
- UI flows (token modal, txt2img, img2img, history) all pass
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: Colab verification results"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| Scope & non-goals | reflected in task selection |
| Architecture diagram | Tasks 3, 6, 12 (store, worker, main) |
| Startup sequence | Task 18 (run_colab.py) |
| API: POST /tasks/txt2img | Task 8 |
| API: POST /tasks/img2img | Task 9 |
| API: GET /tasks/{id} | Task 10 |
| API: GET /tasks/{id}/image | Task 11 |
| API: GET /healthz | Task 7 |
| API: GET / | Task 14 |
| Web UI: token management | Task 14 |
| Web UI: submit flow | Task 15 |
| Web UI: history | Task 17 |
| Web UI: quota handling | Task 17 (writeHistory with QuotaExceededError fallback) |
| Error handling: Pydantic 400/422 | Task 2 |
| Error handling: 401 | Task 4 |
| Error handling: 404/409 | Tasks 10, 11 |
| Error handling: 413 | Task 2 (MAX_INIT_IMAGE_BYTES check) |
| Worker task-level isolation | Task 6 |
| OOM cache clear | Task 6 (`_try_empty_cuda_cache`) |
| TaskStore with async lock | Task 3 |
| FluxPipelineHolder (real) | Task 13 |
| Project file structure | matches "File Structure" section |
| Success criteria | Task 19 manual verification |

**2. Placeholder scan:** no TBD/TODO; every code step contains the actual code. Task 16 is documentation-only by design (no code duplication with Task 15).

**3. Type consistency:**
- `TaskRecord` fields defined in Task 3 match usage in Tasks 6, 8, 9, 10, 11.
- `PipelineProtocol.generate(kind, params) -> PIL.Image.Image` consistent across Tasks 5 (fake), 6 (worker), 13 (real).
- `register_routes(app, *, store, queue, pipeline, output_dir, input_dir)` signature matches both Task 7 origin and Task 12 caller.
- `set_expected_token`/`require_token` names consistent between Tasks 4 and 12.
- Env var name `FLUX_TOKEN` used in both `app/main.py` (Task 12) and `run_colab.py` (Task 18).
