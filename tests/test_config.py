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
