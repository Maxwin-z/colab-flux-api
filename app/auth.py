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
