# WebSocket Task Protocol — Design

**Date:** 2026-04-18
**Status:** Draft (pending user review)
**Supersedes (partially):** `2026-04-18-colab-flux-image-api-design.md` — REST submission remains; polling-based status retrieval is replaced by WS push in the web UI

## Purpose

Replace the web UI's 1 Hz REST polling of `GET /tasks/{id}` with a single persistent WebSocket connection that supports:

1. Task submission (`txt2img` and `img2img`)
2. Server-pushed status updates (`pending` → `running` → `done` / `failed`)
3. Transparent reconnection with automatic re-subscription

HTTP endpoints are retained for image download, health, the UI shell, and external/curl clients. A single browser session uses one long-lived WS for everything except image bytes.

## Scope

**In scope**
- New endpoint `GET /ws?token=<bearer>` (WebSocket upgrade)
- In-process `SubscriptionHub` for fan-out of task-state snapshots
- Hook in `TaskStore.set_status` that publishes post-change snapshots
- Client-side `WSClient` (vanilla JS, embedded in `index.html`) replacing `pollUntilDone`
- Connection status indicator in the UI header

**Non-goals**
- Removing REST endpoints (`POST /tasks/{kind}`, `GET /tasks/{id}` stay — used by curl / external callers)
- Server-side persistence of WS state across process restarts
- Step-level progress events, queue-position change events
- Custom application-layer heartbeat (rely on uvicorn ping/pong)
- Backpressure / flow control beyond what uvicorn provides
- Idempotency keys / submit deduplication

## Key decisions

| Concern | Decision | Rationale |
|---|---|---|
| Connection topology | Single long-lived WS per browser; messages keyed by `task_id` | Low overhead, natural multi-task subscription, future-proof for any bi-directional interaction |
| Reconnect semantics | On `subscribe`, server immediately pushes current snapshot, then incremental events | `TaskRecord` is already a self-contained snapshot — `store.get()` + send is trivial |
| Event granularity | State transitions only (`pending` / `running` / `done` / `failed`) | Schnell is 3–5s end-to-end; queue-position and step-level events are YAGNI |
| Auth | Bearer token in query string (`/ws?token=...`) | Browser `new WebSocket()` can't set headers; this tool is single-user, token rotates per Colab session, tunnel URL is ephemeral — log-leak risk is acceptable |
| REST coexistence | Both REST and WS remain; UI prefers WS; REST endpoints unchanged | External curl users keep working; no deprecation phase needed |
| Submit → subscribe | `submit` implicitly subscribes the sender's connection to the new task | Ergonomic: one round-trip; no client-side state machine for "submit-then-subscribe" |
| Terminal auto-unsub | Server removes the subscription after publishing a terminal `state` | Client doesn't need to manage lifecycle; idempotent re-subscribes still work |
| State payload | Identical to `TaskStatusResponse` (REST) | Single render path in the UI; one Pydantic model serves both surfaces |

## Architecture

```
┌──────────┐   HTTP GET /, /healthz, /tasks/{id}/image      ┌────────────────┐
│ Browser  ├──────────────────────────────────────────────► │                │
│    UI    │   HTTP POST /tasks/{kind}     (REST retained)  │   FastAPI      │
│          ├──────────────────────────────────────────────► │   (Colab :8000)│
│          │   WS   /ws?token=...                           │                │
│          │◄──────────────────────────────────────────────►│                │
└──────────┘                                                 └───┬────────────┘
                                                                 │
                                                 ┌───────────────┼─────────────────┐
                                                 ▼               ▼                 ▼
                                          SubscriptionHub     TaskStore      asyncio.Queue
                                          (task_id →           (unchanged      (unchanged)
                                           set[WebSocket])      + on_change           │
                                                 ▲              callback)             ▼
                                                 │                              Worker coroutine
                                                 │                                    │
                                                 └────── publish(task_id, snap) ◄─────┘
                                                         (fired by store on set_status)
```

## Protocol

All messages are JSON text frames. `type` is the discriminator. Client messages include a client-generated `req_id` to correlate replies.

### Client → Server

```json
// Submit a new task; implicitly subscribes this connection.
{
  "type": "submit",
  "req_id": "c1",
  "kind": "txt2img" | "img2img",
  "params": {
    "prompt": "...",
    "width": 1024, "height": 1024,
    "num_inference_steps": 4,
    "seed": null,
    "strength": 0.7,              // img2img only
    "init_image": "<base64>"      // img2img only
  }
}

// Subscribe to an existing task (reconnect / history-click flow).
{ "type": "subscribe",   "req_id": "c2", "task_id": "abc..." }

// Cancel a subscription (client-side abandon).
{ "type": "unsubscribe", "task_id": "abc..." }
```

### Server → Client

```json
// Reply to submit.
{ "type": "submitted", "req_id": "c1", "task_id": "abc..." }

// State snapshot. Sent:
//   (1) immediately after a successful subscribe / submit (current state)
//   (2) after every TaskStore.set_status for subscribed tasks
{
  "type": "state",
  "task_id": "abc...",
  "kind": "txt2img",
  "status": "pending" | "running" | "done" | "failed",
  "created_at": "...",
  "started_at":  null | "...",
  "finished_at": null | "...",
  "queue_position": null | 2,     // only when status == "pending"
  "image_url":     null | "/tasks/abc.../image",
  "error":         null | "..."
}

// Protocol or validation error. Connection remains open.
{
  "type": "error",
  "req_id": "c1" | null,
  "code": "validation" | "not_found" | "internal",
  "message": "..."
}
```

### Semantics

- **`submit` is atomic**: validate → create task → enqueue → subscribe this WS → send `submitted` → send first `state` (always `pending`). If validation fails, none of the later steps run and the client gets `error {code: "validation"}`.
- **`subscribe` to a known task**: atomically add to hub, then read current state from store, then send one `state`. If that state is terminal, immediately remove the subscription before returning.
- **`subscribe` to an unknown task**: `error {code: "not_found"}`; subscription is not added.
- **Terminal auto-unsub**: after publishing a `state` with `status in ("done", "failed")`, the hub removes every subscription for that task. Clients do not need to `unsubscribe`.
- **State payload is a full snapshot, not a delta**: duplicate or out-of-order sends are harmless — client takes the latest value of each field.
- **Payload size**: `params.init_image` is base64-encoded bytes, capped at 10 MB decoded (same as REST). `ws_max_size` is set to 16 MB explicitly in uvicorn config. A message exceeding this is closed by uvicorn with code 1009; the client handles it as a failed submit.
- **Auth failure**: closed during handshake with close code 4401. Already-accepted connections do not re-authenticate.
- **Heartbeat**: uvicorn's WebSocket ping/pong only; no app-level keepalive messages.

## Server modules

### `app/ws_hub.py` (new) — `SubscriptionHub`

Pure in-memory fan-out structure. One responsibility: deliver a payload to every WebSocket currently subscribed to a given `task_id`.

```python
class SubscriptionHub:
    def __init__(self) -> None:
        self._subs: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, task_id: str, ws: WebSocket) -> None: ...
    async def unsubscribe(self, task_id: str, ws: WebSocket) -> None: ...
    async def drop_connection(self, ws: WebSocket) -> None:
        """Remove ws from every task's subscription set. Called on disconnect."""
    async def publish(self, task_id: str, payload: dict) -> None:
        """Send payload as JSON text to each subscriber. On send failure,
        silently drop that subscription and continue with the rest."""
```

Concurrency:
- `_lock` protects only the subscription table. `publish` copies the subscriber set inside the lock, then fans out `send_json` calls outside the lock with `asyncio.gather(..., return_exceptions=True)`. Failed sends are re-acquired on the lock and removed from the set.
- The hub does not know about `state` / `error` / `submitted` shapes — it just broadcasts `dict` → JSON.

### `app/store.py` — `TaskStore` change (minimal)

```python
class TaskStore:
    def __init__(
        self,
        on_change: Callable[[TaskRecord], Awaitable[None]] | None = None,
    ) -> None:
        ...
        self._on_change = on_change

    async def set_status(self, task_id: str, **updates: Any) -> None:
        async with self._lock:
            ...  # mutate as today
            record = self._records[task_id]
        if self._on_change is not None:
            await self._on_change(record)   # outside the lock
```

`main.py` wires `on_change = lambda rec: hub.publish(rec.task_id, to_snapshot_dict(rec))`, where `to_snapshot_dict` reuses the `TaskStatusResponse` serialization used by REST.

Notes:
- `TaskStore.create(...)` does **not** invoke the callback. The initial `pending` snapshot is sent by the WS submit handler, synchronously within the handler, after it has added the WS to the hub. This avoids races between "publish from create" and "subscribe after create".
- `on_change` runs outside the store lock so a slow `publish` cannot block subsequent `set_status` calls.

### `app/ws.py` (new) — `/ws` endpoint

```python
async def ws_endpoint(ws, hub, store, queue, pipeline, input_dir, expected_token):
    # 1) Auth during handshake
    if ws.query_params.get("token") != expected_token:
        await ws.close(code=4401)
        return
    await ws.accept()

    try:
        while True:
            msg = await ws.receive_json()
            match msg.get("type"):
                case "submit":      await _handle_submit(...)
                case "subscribe":   await _handle_subscribe(...)
                case "unsubscribe": await _handle_unsubscribe(...)
                case _:             await ws.send_json(_error(msg.get("req_id"),
                                        "validation", f"unknown type {msg.get('type')!r}"))
    except WebSocketDisconnect:
        pass
    finally:
        await hub.drop_connection(ws)
```

**`_handle_submit`**
1. Validate `kind` + `params` with existing `TxtToImgRequest` / `ImgToImgRequest`. Failure → `error {code: "validation"}`, return.
2. Generate `task_id`. For `img2img`, decode and write base64 to `input_dir / f"{task_id}.png"` (same as today's REST path).
3. `await store.create(record)`
4. `await hub.subscribe(task_id, ws)`  (**before** enqueueing, so we cannot miss a state change)
5. `await ws.send_json({"type": "submitted", "req_id": req_id, "task_id": task_id})`
6. `await ws.send_json({"type": "state", **to_snapshot_dict(record)})`
7. `await queue.put(task_id)`

**`_handle_subscribe`**
1. `rec = store.get(task_id)`; if `None` → `error {code: "not_found"}`, return
2. `await hub.subscribe(task_id, ws)`
3. `await ws.send_json({"type": "state", **to_snapshot_dict(rec)})`
4. If `rec.status in ("done", "failed")`, `await hub.unsubscribe(task_id, ws)`

**`_handle_unsubscribe`**: `await hub.unsubscribe(task_id, ws)`. Idempotent.

### `app/routes.py` / `app/main.py` changes

- Split out `register_ws(app, *, hub, store, queue, pipeline, input_dir, expected_token)` into `app/ws.py`; keep REST routes in `routes.py`. Two register calls from `main.py`.
- `main.py` lifespan: `hub = SubscriptionHub()` → `store = TaskStore(on_change=...)` → `queue` / `pipeline` / `worker` as today → `register_routes(...)` → `register_ws(...)`.
- `pipeline.py` and `queue_worker.py` are unchanged.

## Client

The entire client change is local to `app/static/index.html`.

### `WSClient`

Singleton long-lived connection wrapping the browser's `WebSocket`.

**Responsibilities**
1. Connect on page load to `/ws?token=<localStorage.flux_token>`.
2. Auto-reconnect on close with exponential backoff: 1 s → 2 s → 4 s → 8 s, capped at 30 s. Immediate reconnect if the token is replaced.
3. Expose `submit(...)`, `subscribe(...)`, `unsubscribe(...)`, each returning a `Subscription` handle.
4. On reconnect, for every entry in `activeSubs: Map<task_id, Subscription>`, re-send `subscribe {task_id}` so the server pushes fresh snapshots transparently.
5. Maintain a header status indicator — **green** (open) / **yellow** (reconnecting) / **red** (closed due to auth failure or missing token).

**Public API**

```js
// Submit + subscribe in one call.
const sub = ws.submit({
  kind: "txt2img",
  params: { prompt, width, height, num_inference_steps, seed, ... },
  onState: (state) => { /* called for every `state` event */ },
});
const task_id = await sub.taskId;   // resolves when `submitted` arrives
const final   = await sub.done;     // resolves with the terminal state, rejects on `failed`

// Subscribe to an existing task (history-click, reconnect after reload).
const sub = ws.subscribe(task_id, { onState });
const final = await sub.done;
// If the task is already terminal server-side, onState fires once and sub.done
// resolves immediately. If it's not_found, sub.done rejects with {code: "not_found"}.

// Client-side cancel (UI navigation, user abandon).
sub.cancel();
```

**Internal structures**
- `pendingReqs: Map<req_id, {resolveTaskId, rejectTaskId}>` — resolves `sub.taskId` when `submitted` arrives.
- `activeSubs: Map<task_id, Subscription>` — routes incoming `state` events; removed on terminal state (auto-resolve `sub.done`) or `cancel()`.

### Reconnect behavior (invariants)

| Scenario | WSClient behavior | User-visible effect |
|---|---|---|
| Page load → connected | Open; indicator green | None |
| Network blip mid-task, disconnect | `activeSubs` kept; indicator yellow | None (stage timer keeps ticking) |
| Reconnect successful | Re-subscribe every `task_id` in `activeSubs`; server pushes current snapshot | None (UI may jump from "running" to "done" if state advanced during outage) |
| Token cleared / invalid | Server closes with code 4401; indicator red; token modal reopens | Prompted to paste token |
| `submit` sent but connection dies before `submitted` | Corresponding `sub.taskId` and `sub.done` both reject ("connection lost before submit confirmed") | Error shown, user retries manually |

The last row is deliberate: auto-replaying unconfirmed submits risks creating duplicate server-side tasks (the first submit might have succeeded, only the reply was lost). Explicit failure is safer than implicit double submission for a 3–5 s job.

### UI integration points

Current `form.addEventListener("submit", ...)`:

```js
const submitted = await apiPost(path, body);
const done = await pollUntilDone(submitted.task_id);
```

becomes:

```js
const sub = ws.submit({
  kind: mode,
  params: body,
  onState: (s) => {
    if (s.status === "running") startStageTimerIfNotStarted();
    else if (s.status === "pending") {
      const pos = s.queue_position ? ` · queue pos ${s.queue_position}` : "";
      setStatus(null, `pending${pos}`);
    }
  },
});
const done = await sub.done;
```

Downstream code is unchanged: `done.image_url`, `done.started_at`, `done.finished_at` match the current `TaskStatusResponse` shape byte-for-byte.

History-click path `showHistoryEntry(entry)`:
- Today: `apiGet('/tasks/${id}/image')`, show thumbnail if 404/409.
- New: `await ws.subscribe(entry.task_id).done` → on terminal `done`, use `image_url` for the HTTP fetch; on `not_found` (server forgot the task), fall back to thumbnail-only. Same data path as fresh generation, less branching.

### Connection indicator

Extend the header:

```
[● connected] [● token set]   [Clear]
```

Three colors: green / yellow / red (see table above). No reconnect countdown, no progress bar.

## Error handling

| Layer | Trigger | Handling |
|---|---|---|
| Handshake | Missing / invalid `?token=` | `ws.close(4401)`; client flips indicator red, shows token modal |
| uvicorn protocol | Message > `ws_max_size` (16 MB) | uvicorn closes with code 1009; client reports the current submit as failed |
| Message parse | Bad JSON, missing `type`, unknown `type` | `error {code: "validation", req_id}`; connection stays open |
| Business validation | Pydantic failure (prompt empty, non-64-multiple size, bad base64, strength out of range) | `error {code: "validation", req_id, message}`; task not created |
| Unknown task | `subscribe {task_id: <unknown>}` | `error {code: "not_found", req_id}`; not added to hub |
| Worker exception | Captured by existing queue_worker into `TaskRecord.status="failed"` | Delivered as a normal `state` event (`status: "failed", error: ...`) — not a WS-level error |
| Unexpected handler exception | Bug in `_handle_*` | Log traceback to stderr; send `error {code: "internal"}`; keep connection open |
| `hub.publish` send failure | Subscriber's WS is already dead | Silently remove that one subscription; other subscribers unaffected |
| Client disconnect | `WebSocketDisconnect` raised in receive loop | `finally: await hub.drop_connection(ws)` clears all of its subscriptions |

### Subscribe / set_status ordering

`_handle_subscribe` order is: (1) add to hub, (2) read store, (3) send snapshot. If `set_status` fires between (1) and (3), the client may receive two `state` messages for the same change. That's fine — `state` is a full snapshot, not a delta. Reversing the order (read then add) would risk missing an event, so we accept the harmless duplicate.

## Testing

All new tests run without a GPU (re-use `FakePipeline` from existing suite).

### New: `tests/test_ws_hub.py`

- Basic `subscribe` / `publish` / `unsubscribe` round-trip with mock WS objects.
- Multiple subscribers on one `task_id` all receive a `publish`.
- `drop_connection` removes a WS from every task's set.
- `publish` where one subscriber's `send_json` raises → only that subscription is dropped; other subscribers receive the payload.

### New: `tests/test_ws_endpoint.py`

Uses FastAPI `TestClient.websocket_connect`.

- **Auth**
  - Missing `?token=` → connect raises / close code 4401
  - Wrong token → same
  - Valid token → `accept`

- **Submit txt2img** (FakePipeline)
  - Send `submit {kind: "txt2img", params: {...}}`; receive `submitted`, then `state {status: "pending"}`.
  - Advance event loop; receive `state {status: "running"}`, then `state {status: "done", image_url}`.
  - `GET /tasks/{id}/image` (REST) returns 200 with the bytes.
  - After terminal state, the server sends nothing further (assert idle for N ms).

- **Subscribe to already-done task**
  - Create a done task via REST path.
  - Connect WS, send `subscribe`; receive exactly one `state {status: "done"}`; then idle.

- **Subscribe to unknown task** → `error {code: "not_found"}`.

- **Validation**
  - `submit` missing `kind` → `error {code: "validation"}`.
  - `submit` with `width=123` (non-multiple-of-64) → `error {code: "validation"}`.
  - Unknown message `type` → `error {code: "validation"}`.

- **Disconnect cleanup**
  - Client subscribes, then closes; server's `hub._subs` no longer contains that WS (test hook on `hub` for introspection).

### Updated: `tests/test_store.py`

- New case: `TaskStore(on_change=callback)` calls `callback(record)` exactly once per `set_status`, outside the store's `_lock`, with the updated record.

### Unchanged

- `tests/test_routes.py`, `tests/test_queue_worker.py`, `tests/test_pipeline_fake.py`, `tests/test_auth.py`, `tests/test_config.py`, `tests/test_schemas.py` — REST behavior is preserved.

## File structure (after change)

```
app/
├── __init__.py
├── main.py              # lifespan: wire hub ↔ store ↔ routes ↔ ws
├── config.py
├── auth.py
├── schemas.py
├── store.py             # + on_change callback
├── queue_worker.py      # unchanged
├── pipeline.py          # unchanged
├── routes.py            # REST endpoints only (unchanged surface)
├── ws.py                # NEW — register_ws + handlers
├── ws_hub.py            # NEW — SubscriptionHub
└── static/index.html    # updated: WSClient + indicator + submit/history integration
```

## Success criteria

**Server**
- `GET /ws?token=<valid>` upgrades; `?token=<wrong>` closes with 4401.
- `submit` followed by worker completion produces exactly three `state` events (`pending`, `running`, `done`) on the submitting connection; no further messages on that task after terminal.
- `subscribe` to a terminal task delivers exactly one `state` and then no further messages.
- Killing a connection mid-subscription leaves `hub._subs` with no trace of it within one event-loop turn.
- REST endpoints (`POST /tasks/*`, `GET /tasks/{id}`, `GET /tasks/{id}/image`, `GET /healthz`) respond identically to before.

**Client**
- Page loads, WS connects, indicator turns green within 1 s under normal conditions.
- Submitting a txt2img task via the form displays an image within ~10 s, with no REST polling observed in network tab.
- Dropping the network for ≤ 30 s mid-task and restoring it: UI eventually shows the final result with no user action.
- Clicking a history item whose task is still on the server shows the image via WS-delivered `image_url`; clicking one that isn't falls back to thumbnail-only.
- Revoking the token (Clear button) drops the WS to red and reopens the token modal.
