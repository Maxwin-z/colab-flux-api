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
