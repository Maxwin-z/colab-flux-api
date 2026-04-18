# FLUX Image Generator — API 文档

本服务在 Colab 上运行 FLUX.1 [schnell]，对外暴露两条协议：

| 协议 | 用途 |
|---|---|
| HTTP REST | 任务提交、状态查询、图片下载、健康检查 |
| WebSocket | 单连接多路订阅：任务提交 + 状态服务端推送 |

两者可自由混用。Web UI 的推荐路径是 WebSocket 提交 + HTTP 下图；外部 curl / 脚本用户走 REST 最省事。

---

## 1. 基本信息

- **协议**：HTTPS（Colab 通过 TryCloudflare 暴露的 `https://*.trycloudflare.com`）。本地开发是 `http://127.0.0.1:8000`。
- **认证**：Bearer token，启动时在 Colab 日志里打印（形如 `uabJ…`）。
- **内容类型**：所有请求/响应均为 `application/json`（下载图片除外，返回 `image/png`）。
- **任务语义**：单 GPU worker，串行处理；提交后进入队列，约 3–5 s 完成一张 1024² 的图。

---

## 2. 认证

### HTTP

```
Authorization: Bearer <TOKEN>
```

- 缺失或错误 → `401 Unauthorized`
- `GET /`、`GET /healthz` 不需要 token
- 其它所有 `/tasks/*` 端点都需要

### WebSocket

浏览器 `new WebSocket()` 不能设 header，所以 token 走 query string：

```
wss://<host>/ws?token=<TOKEN>
```

认证失败时，服务端先 `accept` 握手再用自定义 close code **4401** 主动关闭。浏览器的 `onclose` 事件里可以看到 `event.code === 4401`。

---

## 3. HTTP REST API

### 3.1 提交 txt2img 任务

`POST /tasks/txt2img`

**请求体**

```json
{
  "prompt": "a cat astronaut on the moon",
  "width": 1024,
  "height": 1024,
  "num_inference_steps": 4,
  "guidance_scale": 0.0,
  "seed": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `prompt` | string | 是 | 1–2000 字符 |
| `width` | int | 否，默认 1024 | 256–1536，必须是 64 的倍数 |
| `height` | int | 否，默认 1024 | 同上 |
| `num_inference_steps` | int | 否，默认 4 | 1–8（schnell 最佳为 4） |
| `guidance_scale` | float | 否，默认 0.0 | schnell 推荐 0.0 |
| `seed` | int \| null | 否 | null 表示随机 |

**响应** `202 Accepted`

```json
{ "task_id": "9c4e…", "status": "pending" }
```

**错误**

| 状态码 | 含义 |
|---|---|
| 401 | token 缺失/错误 |
| 422 | 请求体字段校验失败 |

---

### 3.2 提交 img2img 任务

`POST /tasks/img2img`

**请求体**

```json
{
  "prompt": "same cat, cyberpunk style",
  "init_image": "<base64 encoded PNG/JPEG>",
  "strength": 0.7,
  "num_inference_steps": 4,
  "guidance_scale": 0.0,
  "seed": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `prompt` | string | 是 | 1–2000 字符 |
| `init_image` | string | 是 | base64 编码的 PNG/JPEG，解码后 ≤ 10 MB |
| `strength` | float | 否，默认 0.7 | 0.0–1.0，越大越偏离原图 |
| 其余字段 | — | — | 同 txt2img |

服务端会把 `init_image` 解码写到磁盘，**不会在响应里回显**；请求结束后 base64 数据也不保留在内存。

**响应** `202 Accepted`

```json
{ "task_id": "9c4e…", "status": "pending" }
```

**错误**

| 状态码 | 含义 |
|---|---|
| 401 | token 缺失/错误 |
| 422 | 字段校验失败（含 base64 解码失败、尺寸超限、图像格式不认） |

---

### 3.3 查询任务状态

`GET /tasks/{task_id}`

**响应** `200 OK`

```json
{
  "task_id": "9c4e…",
  "kind": "txt2img",
  "status": "pending" | "running" | "done" | "failed",
  "created_at": "2026-04-18T12:00:00+00:00",
  "started_at": null,
  "finished_at": null,
  "queue_position": 2,
  "image_url": null,
  "error": null
}
```

| 字段 | 出现条件 |
|---|---|
| `queue_position` | 仅 `status == "pending"` 时有值，1-based |
| `started_at` | running/done/failed 时填充 |
| `finished_at` | done/failed 时填充 |
| `image_url` | 仅 `status == "done"` 时为 `/tasks/{id}/image` |
| `error` | 仅 `status == "failed"` 时为 `"<ExceptionClass>: <message[:500]>"` |

**错误**

| 状态码 | 含义 |
|---|---|
| 401 | token 缺失/错误 |
| 404 | 未知的 `task_id` |

---

### 3.4 下载生成的图片

`GET /tasks/{task_id}/image`

**响应** `200 OK`

- `Content-Type: image/png`
- Body：PNG 字节流
- `Content-Disposition: attachment; filename="{task_id}.png"`

**错误**

| 状态码 | 含义 |
|---|---|
| 401 | token 缺失/错误 |
| 404 | 未知 `task_id` |
| 409 | 任务还没完成（`status != done`） |

> 生成结果只在 Colab 当前会话的磁盘上。Colab 重启后原有 task_id 不再可用（404）。

---

### 3.5 健康检查

`GET /healthz` —— **不需要认证**。

**响应** `200 OK`

```json
{ "status": "ok", "model_loaded": true, "queue_depth": 2 }
```

`queue_depth` 是 pending + running 的任务数。

---

### 3.6 UI 首页

`GET /` —— **不需要认证**。返回 `text/html`，即内置的单页 Web UI。

---

## 4. WebSocket API

### 4.1 建立连接

```
ws(s)://<host>/ws?token=<TOKEN>
```

- 握手成功：服务端 `accept`，进入就绪状态。
- 握手失败（token 缺/错）：服务端 `accept` 后立刻 `close(code=4401)`，浏览器在 `onclose` 看到 4401。
- 应用层**没有心跳**；依赖 WebSocket 协议层 ping/pong（由 uvicorn 自动处理）。

### 4.2 消息约定

- 所有消息都是 **JSON 文本帧**。
- 客户端消息用 `req_id`（字符串）做关联，`req_id` 完全由客户端生成、不保证全局唯一，只要在单条连接内能辨识即可。
- 载荷最大 **16 MB**（足够容纳 10 MB PNG 的 base64 编码）。

---

### 4.3 客户端 → 服务端

#### `submit` —— 新建任务（隐式订阅）

```json
{
  "type": "submit",
  "req_id": "c1",
  "kind": "txt2img",       // 或 "img2img"
  "params": {
    "prompt": "...",
    "width": 1024,
    "height": 1024,
    "num_inference_steps": 4,
    "seed": null,
    "strength": 0.7,          // 仅 img2img
    "init_image": "<base64>"  // 仅 img2img
  }
}
```

`params` 的字段约束和 REST 的 `POST /tasks/{kind}` 完全一致。提交成功后本连接自动订阅该任务，状态变化会通过 `state` 事件推送，不需要再发 `subscribe`。

#### `subscribe` —— 订阅已有任务

```json
{ "type": "subscribe", "req_id": "c2", "task_id": "9c4e…" }
```

常见用法：
- 浏览器重连后恢复对正在跑的任务的关注；
- 点击历史记录条目时检查任务是否还在服务器上；
- 外部客户端监听由其它渠道提交的任务。

订阅成功后服务端**立即推一条 `state`**（当前快照）；如果该 task 当时已经是终态（`done`/`failed`），服务端在推完这条快照后立刻把该订阅踢掉，之后不会再收到任何消息。

#### `unsubscribe` —— 取消订阅（幂等）

```json
{ "type": "unsubscribe", "task_id": "9c4e…" }
```

---

### 4.4 服务端 → 客户端

#### `submitted` —— `submit` 的回执

```json
{ "type": "submitted", "req_id": "c1", "task_id": "9c4e…" }
```

总在 `submit` 验证通过后立即发送；紧接着会紧跟一条 `state {status: "pending"}`。

#### `state` —— 任务状态快照

```json
{
  "type": "state",
  "task_id": "9c4e…",
  "kind": "txt2img",
  "status": "pending" | "running" | "done" | "failed",
  "created_at": "2026-04-18T12:00:00+00:00",
  "started_at": null | "...",
  "finished_at": null | "...",
  "queue_position": null | 2,
  "image_url": null | "/tasks/9c4e…/image",
  "error": null | "..."
}
```

载荷字段与 REST `GET /tasks/{id}` 完全相同（同一份数据源）。发送时机：

1. 刚 `submit` / `subscribe` 成功 —— 立刻推一条当前快照；
2. 任务状态每次变化 —— 推更新后的快照。

收到 `status in ("done", "failed")` 的 `state` 后，**服务端自动取消该任务在本连接上的订阅**，无需客户端主动 `unsubscribe`；之后不会再收到该 task_id 的任何消息。

#### `error` —— 协议或验证错误

```json
{
  "type": "error",
  "req_id": "c1" | null,
  "code": "validation" | "not_found" | "internal",
  "message": "..."
}
```

| `code` | 触发 |
|---|---|
| `validation` | 消息缺 `type`、`type` 未知、`params` 字段校验失败、未知 `kind` 等 |
| `not_found` | `subscribe` 了一个服务端不认识的 `task_id` |
| `internal` | 服务端处理器抛出未预期异常（不常见） |

**连接在所有 `error` 之后都保持打开**，客户端可以继续发其它消息。

---

### 4.5 生命周期示意

正常 submit 流：

```
C →  {type:"submit", req_id:"c1", kind:"txt2img", params:{...}}
C ←  {type:"submitted", req_id:"c1", task_id:"9c4e…"}
C ←  {type:"state", task_id:"9c4e…", status:"pending", queue_position:1, …}
C ←  {type:"state", task_id:"9c4e…", status:"running", …}
C ←  {type:"state", task_id:"9c4e…", status:"done", image_url:"/tasks/9c4e…/image", …}
                  ⟵ 此后本 task 再也不会有任何消息 ⟶
```

订阅已完成任务：

```
C →  {type:"subscribe", req_id:"c2", task_id:"9c4e…"}
C ←  {type:"state", task_id:"9c4e…", status:"done", image_url:"…"}
                  ⟵ 服务端自动取消订阅，后续无消息 ⟶
```

订阅不存在的任务：

```
C →  {type:"subscribe", req_id:"c3", task_id:"ghost"}
C ←  {type:"error", req_id:"c3", code:"not_found", message:"task ghost not found"}
```

---

### 4.6 断线与重连建议

WebSocket 连接本身不可靠（网络抖动、休眠、代理关闭）。推荐客户端实现：

1. **指数退避重连**：1s → 2s → 4s → …（本仓库前端实现的上限是 30 s）。
2. **重连后自动重订阅**：维护一张 `activeSubs: Map<task_id, 句柄>`，连接 `open` 时对每个 `task_id` 重新发一条 `subscribe`。服务端会立刻推回当前快照，客户端的 UI 无感恢复。
3. **挂起的 submit 不自动重发**：若 `submit` 发出后、收到 `submitted` 前断线，无法确定服务端是否已经创建任务，避免重复提交；应当**显式报错**让用户手动重试。
4. **收到 close code 4401**：说明 token 无效，停止重连、提示用户重新输入 token。

下游图片下载仍走 HTTP —— `state.image_url` 是一个相对路径，直接 `fetch` 即可（记得带 `Authorization` header）。

---

## 5. 示例

### 5.1 curl（REST，轮询）

```bash
TOKEN="<your-token>"
HOST="https://xxxxx.trycloudflare.com"

# 提交
TASK_ID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a cat astronaut", "width":1024, "height":1024}' \
  "$HOST/tasks/txt2img" | jq -r .task_id)

# 轮询
while :; do
  STATE=$(curl -s -H "Authorization: Bearer $TOKEN" "$HOST/tasks/$TASK_ID")
  STATUS=$(echo "$STATE" | jq -r .status)
  echo "status=$STATUS"
  [ "$STATUS" = "done" ] && break
  [ "$STATUS" = "failed" ] && { echo "$STATE" | jq .error; exit 1; }
  sleep 1
done

# 下载
curl -s -o out.png -H "Authorization: Bearer $TOKEN" "$HOST/tasks/$TASK_ID/image"
```

### 5.2 Python（REST，`requests`）

```python
import requests, time

TOKEN = "..."
HOST = "https://xxxxx.trycloudflare.com"
H = {"Authorization": f"Bearer {TOKEN}"}

r = requests.post(f"{HOST}/tasks/txt2img", headers=H,
                  json={"prompt": "a cat astronaut", "width": 1024, "height": 1024})
r.raise_for_status()
task_id = r.json()["task_id"]

while True:
    s = requests.get(f"{HOST}/tasks/{task_id}", headers=H).json()
    if s["status"] == "done":
        break
    if s["status"] == "failed":
        raise RuntimeError(s["error"])
    time.sleep(1)

img = requests.get(f"{HOST}/tasks/{task_id}/image", headers=H).content
open("out.png", "wb").write(img)
```

### 5.3 Python（WebSocket，`websockets` 库）

```python
import asyncio, json, websockets, urllib.request

TOKEN = "..."
HOST  = "xxxxx.trycloudflare.com"

async def generate(prompt):
    async with websockets.connect(f"wss://{HOST}/ws?token={TOKEN}") as ws:
        await ws.send(json.dumps({
            "type": "submit", "req_id": "c1", "kind": "txt2img",
            "params": {"prompt": prompt, "width": 1024, "height": 1024},
        }))
        task_id = None
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == "submitted":
                task_id = msg["task_id"]
            elif msg["type"] == "state" and msg["status"] == "done":
                image_url = msg["image_url"]
                break
            elif msg["type"] == "state" and msg["status"] == "failed":
                raise RuntimeError(msg["error"])
            elif msg["type"] == "error":
                raise RuntimeError(f"{msg['code']}: {msg['message']}")
    # 下载图片仍走 HTTP
    req = urllib.request.Request(f"https://{HOST}{image_url}",
                                 headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req) as r, open("out.png", "wb") as f:
        f.write(r.read())

asyncio.run(generate("a cat astronaut"))
```

### 5.4 JavaScript（浏览器，WebSocket）

```js
const TOKEN = "...";
const ws = new WebSocket(`wss://${location.host}/ws?token=${encodeURIComponent(TOKEN)}`);

ws.addEventListener("open", () => {
  ws.send(JSON.stringify({
    type: "submit",
    req_id: "c1",
    kind: "txt2img",
    params: { prompt: "a cat astronaut", width: 1024, height: 1024 },
  }));
});

ws.addEventListener("message", async (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.type === "submitted") {
    console.log("task id:", msg.task_id);
  } else if (msg.type === "state") {
    console.log(msg.status, msg.queue_position ?? "");
    if (msg.status === "done") {
      const r = await fetch(msg.image_url, { headers: { Authorization: `Bearer ${TOKEN}` } });
      const blob = await r.blob();
      document.querySelector("img#result").src = URL.createObjectURL(blob);
    } else if (msg.status === "failed") {
      console.error(msg.error);
    }
  } else if (msg.type === "error") {
    console.error(msg.code, msg.message);
  }
});

ws.addEventListener("close", (ev) => {
  if (ev.code === 4401) alert("invalid token");
});
```

---

## 6. 错误码速查

### HTTP

| 码 | 含义 |
|---|---|
| 200 | OK |
| 202 | 已受理，任务入队 |
| 401 | token 缺失 / 错误 |
| 404 | task_id 不存在（或图片资源不在） |
| 409 | 图片还没生成完 |
| 413 | `init_image` 解码后超过 10 MB |
| 422 | 字段校验失败（FastAPI 默认） |

### WebSocket 关闭码

| 码 | 含义 |
|---|---|
| 1000 | 正常关闭 |
| 1006 | 异常中断（网络问题） |
| 1009 | 消息超过 16 MB 限制 |
| 4401 | 认证失败（自定义） |

### WebSocket `error.code`

| 码 | 含义 |
|---|---|
| `validation` | 消息或参数校验失败 |
| `not_found` | subscribe 了一个未知的 task_id |
| `internal` | 服务端未预期的异常（请检查 Colab 日志） |

---

## 7. 生命周期备忘

- 所有任务和图片**只存在于当前 Colab 会话**。会话重启 → 一切任务 / 图片 / task_id 都失效。
- 如果 Colab 断开，生成中的任务不会恢复。
- 服务端没有自动清理；长时间运行会累积一份 outputs 目录，可按需自行清理。
