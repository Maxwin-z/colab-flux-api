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
        self._txt2img.enable_model_cpu_offload()
        try:
            self._txt2img.vae.enable_tiling()
        except Exception:
            pass
        try:
            self._txt2img.vae.enable_slicing()
        except Exception:
            pass

        # img2img pipeline reuses the same model weights and offload hooks
        self._img2img = FluxImg2ImgPipeline.from_pipe(self._txt2img)

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
