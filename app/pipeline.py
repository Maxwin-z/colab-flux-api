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
