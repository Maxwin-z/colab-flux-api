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
