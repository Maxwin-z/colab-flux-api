from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.ws_hub import SubscriptionHub


class FakeWS:
    """Stand-in for fastapi.WebSocket. Records every send_json call, and can be
    configured to raise on the next send to simulate a dead client.
    """

    def __init__(self, name: str = "", raise_on_send: BaseException | None = None) -> None:
        self.name = name
        self.sent: list[dict[str, Any]] = []
        self._raise_on_send = raise_on_send

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self._raise_on_send is not None:
            exc, self._raise_on_send = self._raise_on_send, None
            raise exc
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_publish_reaches_single_subscriber():
    hub = SubscriptionHub()
    ws = FakeWS()
    await hub.subscribe("t1", ws)  # type: ignore[arg-type]
    await hub.publish("t1", {"type": "state", "task_id": "t1", "status": "running"})
    assert ws.sent == [{"type": "state", "task_id": "t1", "status": "running"}]


@pytest.mark.asyncio
async def test_publish_fans_out_to_multiple_subscribers():
    hub = SubscriptionHub()
    a, b, c = FakeWS("a"), FakeWS("b"), FakeWS("c")
    await hub.subscribe("t1", a)  # type: ignore[arg-type]
    await hub.subscribe("t1", b)  # type: ignore[arg-type]
    await hub.subscribe("t1", c)  # type: ignore[arg-type]
    await hub.publish("t1", {"type": "state", "status": "done"})
    assert a.sent and b.sent and c.sent
    assert a.sent[0]["status"] == "done"
    assert b.sent[0]["status"] == "done"
    assert c.sent[0]["status"] == "done"


@pytest.mark.asyncio
async def test_publish_ignores_other_tasks():
    hub = SubscriptionHub()
    ws_1 = FakeWS()
    ws_2 = FakeWS()
    await hub.subscribe("t1", ws_1)  # type: ignore[arg-type]
    await hub.subscribe("t2", ws_2)  # type: ignore[arg-type]
    await hub.publish("t1", {"x": 1})
    assert ws_1.sent == [{"x": 1}]
    assert ws_2.sent == []


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    hub = SubscriptionHub()
    ws = FakeWS()
    await hub.subscribe("t1", ws)  # type: ignore[arg-type]
    await hub.unsubscribe("t1", ws)  # type: ignore[arg-type]
    await hub.publish("t1", {"x": 1})
    assert ws.sent == []


@pytest.mark.asyncio
async def test_unsubscribe_is_idempotent():
    hub = SubscriptionHub()
    ws = FakeWS()
    # unsubscribe before subscribe: no error
    await hub.unsubscribe("t1", ws)  # type: ignore[arg-type]
    # subscribe + unsubscribe twice: no error
    await hub.subscribe("t1", ws)  # type: ignore[arg-type]
    await hub.unsubscribe("t1", ws)  # type: ignore[arg-type]
    await hub.unsubscribe("t1", ws)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_drop_connection_removes_ws_from_all_tasks():
    hub = SubscriptionHub()
    ws = FakeWS()
    other = FakeWS()
    await hub.subscribe("t1", ws)  # type: ignore[arg-type]
    await hub.subscribe("t2", ws)  # type: ignore[arg-type]
    await hub.subscribe("t1", other)  # type: ignore[arg-type]
    await hub.drop_connection(ws)  # type: ignore[arg-type]

    await hub.publish("t1", {"x": 1})
    await hub.publish("t2", {"x": 2})
    assert ws.sent == []
    assert other.sent == [{"x": 1}]


@pytest.mark.asyncio
async def test_publish_drops_subscriber_whose_send_raises():
    hub = SubscriptionHub()
    bad = FakeWS(raise_on_send=ConnectionError("boom"))
    good = FakeWS()
    await hub.subscribe("t1", bad)  # type: ignore[arg-type]
    await hub.subscribe("t1", good)  # type: ignore[arg-type]

    # First publish: `bad` raises -> should be removed silently; `good` still gets it.
    await hub.publish("t1", {"x": 1})
    assert good.sent == [{"x": 1}]

    # Second publish: `bad` is gone; only `good` receives.
    await hub.publish("t1", {"x": 2})
    assert good.sent == [{"x": 1}, {"x": 2}]


@pytest.mark.asyncio
async def test_publish_to_unknown_task_is_noop():
    hub = SubscriptionHub()
    # Must not raise even when no one is subscribed to "ghost".
    await hub.publish("ghost", {"x": 1})


@pytest.mark.asyncio
async def test_subscribe_is_idempotent_per_connection():
    hub = SubscriptionHub()
    ws = FakeWS()
    await hub.subscribe("t1", ws)  # type: ignore[arg-type]
    await hub.subscribe("t1", ws)  # type: ignore[arg-type]
    await hub.publish("t1", {"x": 1})
    # Should only be delivered once despite double-subscribe.
    assert ws.sent == [{"x": 1}]
