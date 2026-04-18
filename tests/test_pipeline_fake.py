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
