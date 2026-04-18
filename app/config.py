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
