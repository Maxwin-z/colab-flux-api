# Colab FLUX.1 [schnell] Image Generation API — Design

**Date:** 2026-04-18
**Status:** Approved (pending user spec review)
**Target runtime:** Google Colab Pro, NVIDIA L4 (24GB VRAM)
**Model:** `black-forest-labs/FLUX.1-schnell` via `diffusers`

## Purpose

Run FLUX.1 [schnell] on a Colab L4 and expose a small REST API so external clients can submit text-to-image and image-to-image jobs and poll for results. Internal task queue serializes generation to avoid GPU contention.

## Scope

**In scope**
- Python script deployable to a Colab cell (no notebook checked in)
- REST API for txt2img / img2img submission and status/result retrieval
- Internal FIFO queue; single worker; serial GPU execution
- Public access via TryCloudflare tunnel (zero-config)
- Static Bearer-token auth generated at startup
- Minimal single-page web UI at `/` with browser-local history (thumbnails in `localStorage`)

**Non-goals**
- Multi-user, per-user isolation, quotas
- Server-side task persistence / reconnect recovery after Colab restart
- Batch generation (`n>1`), negative prompts, ControlNet, LoRA, inpainting
- Automatic file cleanup
- Multi-GPU / parallel generation
- Server-side history, search, gallery, sharing
- Frontend build tooling (no bundler, no framework)

## Key decisions

| Concern | Decision | Rationale |
|---|---|---|
| Public ingress | TryCloudflare (zero-config `cloudflared --url`) | Free, no account/domain, no connection/rate limits, URL printed at startup |
| Image delivery | Local file on Colab disk + `GET /tasks/{id}/image` download endpoint | Clean API, avoids bloating JSON with base64; Colab disk lifetime is fine given non-persistent design |
| Notification | REST polling only | schnell generates in 3-5s, polling overhead is negligible; WS/SSE is over-engineering |
| Endpoint shape | Separate `/tasks/txt2img` and `/tasks/img2img` | Clear semantics; Pydantic can enforce mode-specific fields strictly |
| Auth | Static Bearer token, random at startup | Tunnel URL is public; token prevents random GPU abuse; JWT/multi-user is YAGNI |
| Persistence | None (in-memory) | Colab is ephemeral; image files die with the session anyway, so persisting only the queue is misleading |
| Web UI | Single static `index.html`, vanilla JS, served at `/` | Single-user personal tool; no build step keeps repo simple; matches the "one Colab cell to run" constraint |
| UI history | Browser `localStorage` only (thumbnails + params) | Survives Colab restarts (history is client-side); full-res images may be lost with Colab session, which is acceptable |

## Architecture

```
Browser (UI @ /)  ─┐
                   ├─HTTPS──► TryCloudflare tunnel ──► FastAPI (Colab :8000)
External client ──┘                                          │
                           ┌─────────────────────────────────┼─────────────────────┐
                           ▼                                 ▼                     ▼
                  Static UI (index.html)             Auth middleware         TaskStore
                  GET /, no auth                     (Bearer token)        (dict + Lock)
                                                            │                     │
                                                            ▼                     ▼
                                                    Routes: /tasks/*        asyncio.Queue
                                                                                  │
                                                                                  ▼
                                                                    Worker coroutine (single)
                                                                                  │
                                                                       asyncio.to_thread
                                                                                  │
                                                                                  ▼
                                                                       FluxPipelineHolder
                                                                          (FLUX.1-schnell on L4)
                                                                                  │
                                                                                  ▼
                                                                  /content/outputs/{task_id}.png
```

**Startup sequence (`run_colab.py`)**
1. Generate random API token (`secrets.token_urlsafe(32)`), print it
2. Launch `cloudflared --url http://localhost:8000` as a subprocess, scrape its stderr for the `*.trycloudflare.com` URL, print it
3. `uvicorn.run("app.main:app", host="0.0.0.0", port=8000)`

**FastAPI lifespan**
- On startup: instantiate `FluxPipelineHolder` and load model weights (~30s one-time), launch worker coroutine
- On shutdown: cancel worker, release pipeline

## API contract

All task endpoints require `Authorization: Bearer <token>`. Missing/wrong token → `401`.

### `POST /tasks/txt2img`

Request:
```json
{
  "prompt": "a cat astronaut",
  "width": 1024,
  "height": 1024,
  "num_inference_steps": 4,
  "guidance_scale": 0.0,
  "seed": null
}
```

- `prompt`: required, 1-2000 chars
- `width`, `height`: optional, default 1024, range 256-1536, must be multiples of 64
- `num_inference_steps`: optional, default 4, range 1-8 (schnell is a 4-step distilled model)
- `guidance_scale`: optional, default 0.0 (schnell recommended)
- `seed`: optional, null for random; if provided, int

Response: `202 Accepted`
```json
{ "task_id": "9c4e...", "status": "pending" }
```

### `POST /tasks/img2img`

Request:
```json
{
  "prompt": "...",
  "init_image": "<base64 PNG/JPEG>",
  "strength": 0.7,
  "num_inference_steps": 4,
  "guidance_scale": 0.0,
  "seed": null
}
```

- `init_image`: required, base64-encoded PNG/JPEG, decoded size ≤ 10MB (413 otherwise)
- `strength`: optional, default 0.7, range 0.0-1.0
- Other fields same as txt2img

On acceptance the server decodes the base64 and writes it to `/content/inputs/{task_id}.png`; the request body is not retained in memory.

Response: `202 Accepted` (same shape as txt2img).

### `GET /tasks/{id}`

Response:
```json
{
  "task_id": "...",
  "kind": "txt2img" | "img2img",
  "status": "pending" | "running" | "done" | "failed",
  "created_at": "2026-04-18T12:00:00Z",
  "started_at": null,
  "finished_at": null,
  "queue_position": 3,
  "image_url": "/tasks/.../image",
  "error": null
}
```

- `queue_position` present only when `status == "pending"`, computed as count of pending tasks created at-or-before this one, plus one
- `image_url` present only when `status == "done"`
- `error` present only when `status == "failed"`
- `404` if task_id unknown

### `GET /tasks/{id}/image`

- `200 image/png` with the rendered image bytes
- `409 Conflict` if `status != done`
- `404` if task_id unknown

### `GET /healthz`

No auth required.
```json
{ "status": "ok", "model_loaded": true, "queue_depth": 2 }
```

### `GET /`

No auth required. Returns the static `index.html` (the single-page UI). The UI itself calls the authenticated `/tasks/*` endpoints with a token stored in `localStorage`.

## Web UI (`GET /`)

Single HTML file served by FastAPI as a static response; no bundler, no framework, vanilla JS + modern CSS only.

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ FLUX Image Generator           [token: set ✓]  [clear token]     │
├───────────────┬──────────────────────────────────────────────────┤
│               │  [ txt2img | img2img ]  (mode toggle)            │
│   History     │                                                  │
│   (thumbs)    │  Prompt: [______________________________________]│
│               │                                                  │
│  ┌──┐ ┌──┐    │  Size: [1024]×[1024]  Steps: [4]  Seed: [random] │
│  │  │ │  │    │  [img2img only: file picker, strength slider]    │
│  └──┘ └──┘    │                                                  │
│  ┌──┐ ┌──┐    │  [ Generate ]                                    │
│  │  │ │  │    │                                                  │
│  └──┘ └──┘    │  ┌────────────────────────────────────────────┐ │
│               │  │  Status: running (step ~2s)                │ │
│               │  │  ┌──────────────────────────┐              │ │
│               │  │  │                          │              │ │
│               │  │  │     result image         │              │ │
│               │  │  │                          │              │ │
│               │  │  └──────────────────────────┘              │ │
│               │  │  [Download]  [Re-run with same params]     │ │
│               │  └────────────────────────────────────────────┘ │
└───────────────┴──────────────────────────────────────────────────┘
```

### Behavior

**Token management**
- On first load, if `localStorage.flux_token` is empty, show a modal prompting the user to paste the token (printed in Colab logs at startup)
- Header shows `[token: set ✓]` with a `[clear token]` button that wipes `localStorage.flux_token` and re-prompts
- All `/tasks/*` calls include `Authorization: Bearer <token>` from localStorage
- On `401` response, clear the token and re-prompt

**Submit flow**
1. User picks mode (`txt2img` / `img2img`), fills form
2. For img2img, selected file is read with `FileReader.readAsDataURL`, base64 payload extracted, sent in `init_image`
3. `POST /tasks/{kind}` → get `task_id`
4. Poll `GET /tasks/{task_id}` at 1 Hz; render `status` and `queue_position` live
5. On `status=done`, `fetch(image_url)` → create blob URL → show in `<img>`
6. Save entry to history (see below)
7. On `status=failed`, show `error` inline

**History (localStorage, client-side only)**
- Key: `flux_history`, value: array of entries, newest first, cap at **50 entries**
- Each entry:
  ```json
  {
    "task_id": "...",
    "kind": "txt2img" | "img2img",
    "prompt": "...",
    "params": { "width": 1024, "height": 1024, "num_inference_steps": 4, "seed": 12345, ... },
    "thumbnail": "data:image/jpeg;base64,...",   // 256px JPEG quality 0.7, ~20-30 KB
    "created_at": "2026-04-18T12:00:00Z"
  }
  ```
- Thumbnail generated client-side from the result image using a canvas (longest edge 256 px, JPEG quality 0.7)
- When a history item is clicked:
  - If the Colab server still has the image (`GET /tasks/{id}/image` returns 200): show full-res result
  - If it returns 404/409: show the thumbnail with a "full image no longer available" note
  - `[Re-run with same params]` button re-populates the form (does NOT automatically re-submit). For img2img entries, the init image itself is NOT stored in history (too large); the user must re-select the file before submitting.
- History survives Colab session restarts (it's entirely client-side)
- `[clear history]` button in the sidebar header wipes `flux_history`

### Quota and size constraints
- Cap 50 history entries × ~30 KB thumbnails ≈ 1.5 MB — well under the 5 MB `localStorage` limit on most browsers
- If `localStorage.setItem` throws `QuotaExceededError`, drop the oldest entries until it fits

### Non-UI behaviors we explicitly don't do
- No server-side rendering, no WebSockets; polling only (1 Hz) to stay consistent with the REST design
- No account/login; same token shared by UI and external clients
- No tag/search/favorite on history; just reverse-chronological thumbnails

## Task queue & worker

### `TaskRecord`
```python
@dataclass
class TaskRecord:
    task_id: str
    kind: Literal["txt2img", "img2img"]
    status: Literal["pending", "running", "done", "failed"]
    params: dict              # resolved params (init_image stored as file path, not bytes)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result_path: str | None
    error: str | None
```

### `TaskStore`
- In-memory `dict[str, TaskRecord]`
- `asyncio.Lock` for writes; reads are dict lookups
- Methods: `create(record)`, `get(task_id)`, `set_status(task_id, **updates)`, `queue_position(task_id)`

### `worker_loop()`
```
while True:
    task_id = await queue.get()
    record = store.get(task_id)
    store.set_status(task_id, status="running", started_at=now())
    try:
        image = await asyncio.to_thread(pipeline.generate, record.kind, record.params)
        path = f"/content/outputs/{task_id}.png"
        image.save(path)
        store.set_status(task_id, status="done", finished_at=now(), result_path=path)
    except Exception as e:
        log_full_traceback_to_stderr(e)
        store.set_status(task_id, status="failed", finished_at=now(),
                         error=f"{type(e).__name__}: {str(e)[:500]}")
        if isinstance(e, torch.cuda.OutOfMemoryError):
            torch.cuda.empty_cache()
    finally:
        queue.task_done()
```

Key properties:
- Single worker + `asyncio.to_thread` → strict serial GPU usage
- Worker never crashes; any exception is recorded on the task and the loop continues
- OOM triggers `empty_cache()` so the next task has a chance

### `FluxPipelineHolder`
- Loads `FLUX.1-schnell` with `torch_dtype=torch.bfloat16`, moves to `cuda`
- Enables `vae_tiling` (safety for 1536×1536) and optionally `enable_model_cpu_offload` only if we see OOM in practice
- Exposes `generate(kind, params) -> PIL.Image` — picks txt2img or img2img pipeline internally

## Error handling

**Request-time (sync responses)**
- `400`: Pydantic validation (size not multiple of 64, strength out of range, base64 decode fail, image parse fail via PIL)
- `401`: token missing/wrong
- `404`: unknown task_id
- `409`: image requested before task is `done`
- `413`: decoded init_image > 10MB

**Worker-time (recorded on task)**
- Any pipeline exception → `status=failed`, `error=<type>: <message[:500]>`, full traceback to Colab stderr only
- `torch.cuda.OutOfMemoryError` → same + `empty_cache()`

**Process-level**
- cloudflared subprocess exits unexpectedly → `run_colab.py` exits non-zero so Colab shows the failure loudly
- Model load fails at startup → fail-fast before listening

**Concurrency**
- Task IDs are server-generated UUIDv4 → no client-side duplication
- TaskStore writes protected by `asyncio.Lock`
- Reads on dict are safe under CPython GIL

## File structure

```
llm-image-generator/
├── README.md                # Colab run instructions
├── requirements.txt         # torch, diffusers, transformers, fastapi, uvicorn,
│                            # pillow, accelerate, sentencepiece
├── run_colab.py             # Entry: generate token, start cloudflared, run uvicorn
└── app/
    ├── __init__.py
    ├── main.py              # FastAPI app + lifespan
    ├── config.py            # paths, defaults, token generation
    ├── auth.py              # Bearer token middleware
    ├── schemas.py           # Pydantic request/response models
    ├── store.py             # TaskStore
    ├── queue_worker.py      # worker_loop
    ├── pipeline.py          # FluxPipelineHolder
    ├── routes.py            # endpoints (/tasks/*, /healthz, /)
    └── static/
        └── index.html       # single-page UI (HTML + inline CSS + inline JS)
```

Single-responsibility per file. `pipeline.py` is the only module that imports torch/diffusers; everything else is protocol-level and testable without a GPU.

## Dependencies

```
torch>=2.2
diffusers>=0.30
transformers>=4.44
accelerate>=0.33
sentencepiece
fastapi>=0.115
uvicorn[standard]>=0.30
pillow
pydantic>=2
```

`cloudflared` is a separate binary fetched by `run_colab.py` at runtime (no pip package).

## Open questions (deferred)

- Cleanup policy for `/content/outputs/*` (MVP: none)
- Whether to expose step-level progress (MVP: no; add SSE later if desired)
- Whether to support optional `negative_prompt` / `max_sequence_length` (MVP: no)

## Success criteria

**API**
- `POST /tasks/txt2img` returns `202` within <50ms
- End-to-end 1024×1024 txt2img completes in ≤10s on L4 (typical 3-5s pipeline + queue/serialization overhead)
- Worker survives any single task failure
- Client can reliably poll `GET /tasks/{id}` at 1Hz without hitting tunnel limits
- Bearer token check blocks unauthorized requests

**UI**
- `GET /` loads `index.html` with no auth
- First visit prompts for token; subsequent visits reuse `localStorage`
- `401` response clears stored token and re-prompts
- txt2img submission from UI yields displayed image within ~10s of clicking Generate
- History persists across page refreshes and Colab restarts
- History capped at 50 entries with oldest-first eviction on quota exceeded
