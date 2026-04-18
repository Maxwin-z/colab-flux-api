"""In-memory subscription fan-out for task-state snapshots.

The hub is deliberately dumb: it knows nothing about task state, payload shape,
or protocol. Its only job is: given a task_id, send a JSON payload to every
WebSocket currently subscribed to that task_id. If a send fails, the offending
subscriber is silently dropped; other subscribers are unaffected.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol


logger = logging.getLogger(__name__)


class _WSLike(Protocol):
    async def send_json(self, payload: dict[str, Any]) -> None: ...


class SubscriptionHub:
    def __init__(self) -> None:
        self._subs: dict[str, set[Any]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, task_id: str, ws: _WSLike) -> None:
        async with self._lock:
            self._subs.setdefault(task_id, set()).add(ws)

    async def unsubscribe(self, task_id: str, ws: _WSLike) -> None:
        async with self._lock:
            subs = self._subs.get(task_id)
            if subs is None:
                return
            subs.discard(ws)
            if not subs:
                del self._subs[task_id]

    async def drop_connection(self, ws: _WSLike) -> None:
        """Remove ws from every task's subscription set. Called on disconnect."""
        async with self._lock:
            empty_keys: list[str] = []
            for task_id, subs in self._subs.items():
                subs.discard(ws)
                if not subs:
                    empty_keys.append(task_id)
            for k in empty_keys:
                del self._subs[k]

    async def publish(self, task_id: str, payload: dict[str, Any]) -> None:
        """Send payload to each subscriber. On send failure, silently drop that
        subscription and continue.
        """
        async with self._lock:
            subs = list(self._subs.get(task_id, ()))
        if not subs:
            return

        results = await asyncio.gather(
            *(ws.send_json(payload) for ws in subs),
            return_exceptions=True,
        )

        dead: list[Any] = [
            ws for ws, res in zip(subs, results) if isinstance(res, BaseException)
        ]
        if not dead:
            return

        for ws in dead:
            logger.debug("dropping ws subscription for task %s: send failed", task_id)
        async with self._lock:
            subs_now = self._subs.get(task_id)
            if subs_now is None:
                return
            for ws in dead:
                subs_now.discard(ws)
            if not subs_now:
                del self._subs[task_id]
