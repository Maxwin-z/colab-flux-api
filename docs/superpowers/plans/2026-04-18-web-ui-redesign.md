# Web UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `app/static/index.html` into a three-column dark UI (history · image stage · controls) with render-duration display in three places, following `docs/superpowers/specs/2026-04-18-web-ui-redesign-design.md`.

**Architecture:** Single-file rewrite — HTML + inline CSS + inline JS. No build step, no framework, no new runtime dependencies. Backend untouched. History schema gains one optional additive field (`duration_ms`) with no migration required.

**Tech Stack:** Vanilla JS, CSS custom properties, native `<input>` styling, inline SVG icons. System font stack with `Inter` as first preference.

**Project status:** This repo is not a git repository at the time of planning. Commit steps are omitted; each task ends with a manual visual verification instead. If `git init` is run later, the user can add commits retroactively.

**Dev loop:** Run the app locally with the fake pipeline:
```bash
source .venv/bin/activate
FLUX_TOKEN=dev uvicorn 'app.main:app' --reload --port 8000
# OR, if the auto-create guard in app/main.py skips it:
python -c "import uvicorn; from app.main import create_app; uvicorn.run(create_app(use_fake_pipeline=True, token='dev'), port=8000)"
```
Open http://localhost:8000 and paste `dev` as the token.

---

## File Structure

Only one file changes:

- **Modify:** `app/static/index.html` — full rewrite of `<style>`, `<body>`, and parts of `<script>`. The JS keeps its existing module-ish split (token section, mode section, API helpers, submit handler, history section) but gains:
  - `formatDuration(ms)` helper
  - live elapsed-time timer
  - dice button wire-up
  - `duration_ms` stored in history entries
  - `⌘/Ctrl + Enter` submit shortcut
  - `Esc` closes token modal

No other files are created or modified.

---

## Task 1: Foundation — tokens, typography, three-column layout shell

Set up the design-system foundations and the three-column grid. After this task the page renders in dark mode with three empty columns and a header, but functionality still works because we keep the existing markup for form / history / result inside those columns temporarily.

**Files:**
- Modify: `app/static/index.html` — replace `<style>` content, wrap existing `<header>`, `<aside>`, `<main>` in the new grid, keep form/history/result markup intact inside the main column for now.

- [ ] **Step 1: Replace the `<style>` block**

Open `app/static/index.html` and replace lines 7–33 (the `<style>…</style>` block) with this complete new block:

```html
<style>
  :root {
    --bg: #141416;
    --surface: #1c1c21;
    --surface-2: #25252c;
    --border: #2d2d35;
    --text: #e8e8ec;
    --text-dim: #8a8a93;
    --text-mute: #5c5c66;
    --accent: #8b7dd8;
    --accent-hover: #a195e8;
    --accent-dim: #8b7dd822;
    --danger: #c9506a;
    --success: #7dd89e;

    --radius-sm: 4px;
    --radius: 8px;
    --radius-lg: 12px;

    font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.45;
    color: var(--text);
    background: var(--bg);
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    min-height: 100vh;
    display: grid;
    grid-template-columns: 240px 1fr 340px;
    grid-template-rows: 48px 1fr;
    grid-template-areas:
      "header header header"
      "history stage controls";
  }

  header {
    grid-area: header;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 16px;
    border-bottom: 1px solid var(--border);
    background: var(--bg);
  }

  aside#history-pane {
    grid-area: history;
    border-right: 1px solid var(--border);
    background: var(--surface);
    overflow-y: auto;
    padding: 16px 12px;
  }

  main {
    grid-area: stage;
    overflow-y: auto;
    padding: 32px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    background: var(--bg);
  }

  section#controls {
    grid-area: controls;
    border-left: 1px solid var(--border);
    background: var(--surface);
    overflow-y: auto;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .section-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-dim);
    margin: 0 0 8px 0;
  }

  .mono {
    font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  }

  input, textarea, select, button {
    font: inherit;
    color: inherit;
  }

  input[type="text"], input[type="number"], input[type="password"], textarea {
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: 8px 10px;
    width: 100%;
    outline: none;
    transition: border-color 120ms, box-shadow 120ms;
  }

  input[type="text"]::placeholder,
  input[type="number"]::placeholder,
  input[type="password"]::placeholder,
  textarea::placeholder { color: var(--text-mute); }

  input:focus, textarea:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-dim);
  }

  button { cursor: pointer; }

  .ghost-btn {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-dim);
    padding: 4px 10px;
    font-size: 12px;
    transition: color 120ms, border-color 120ms, background 120ms;
  }
  .ghost-btn:hover { color: var(--text); border-color: var(--text-dim); background: var(--surface-2); }

  .hidden { display: none !important; }
</style>
```

- [ ] **Step 2: Wrap existing markup with IDs for the grid areas**

Inside `<body>`, keep the existing content but make sure:
- The top `<header>` element is the first child of `<body>`.
- The history `<aside>` has `id="history-pane"` (already does).
- Wrap the existing form + result area inside `<main>` (already does).
- Add a placeholder `<section id="controls">` AFTER `<main>` with a single line of text inside: `<div class="section-label">controls go here (task 5)</div>`. Leave the form inside `<main>` for now — it will move into `<section id="controls">` in Task 5.

Full expected `<body>` markup at the end of this step:

```html
<body>
  <header>
    <strong>FLUX Image Generator</strong>
    <div>
      <span id="token-indicator">token: not set</span>
      <button id="clear-token-btn" type="button">clear token</button>
    </div>
  </header>

  <aside id="history-pane">
    <h3>History <button id="clear-history-btn" type="button" style="font-size:0.7rem;float:right;">clear</button></h3>
    <div id="history-list"></div>
  </aside>

  <main>
    <div class="mode-toggle">
      <button type="button" data-mode="txt2img" class="active">txt2img</button>
      <button type="button" data-mode="img2img">img2img</button>
    </div>

    <form id="gen-form">
      <!-- unchanged from current file, keep everything as-is -->
    </form>

    <div id="result">
      <!-- unchanged from current file, keep everything as-is -->
    </div>
  </main>

  <section id="controls">
    <div class="section-label">controls go here (task 5)</div>
  </section>

  <!-- token modal, scripts, etc. unchanged -->
</body>
```

- [ ] **Step 3: Start the dev server and verify**

Run:
```bash
FLUX_TOKEN=dev uvicorn 'app.main:app' --reload --port 8000
```
(If that fails because `app/main.py` only auto-creates in Colab, run:
```bash
python -c "import uvicorn; from app.main import create_app; uvicorn.run(create_app(use_fake_pipeline=True, token='dev'), port=8000)"
```
)

Open http://localhost:8000. Expected:
- Page is dark (#141416 background).
- Three columns visible: narrow left history panel, wide center area with the old form/result, narrow right control panel with "controls go here (task 5)".
- 48px header across the top with title and token controls.
- Existing form still works (paste `dev` as token, submit a prompt, see an image from the fake pipeline).

- [ ] **Step 4: End-of-task checkpoint**

Visual sanity check only — no automated test exists for the UI. Note any regressions against the checklist before moving on:
- Dark background ✓
- Three columns ✓
- Header at top ✓
- Form submission still works ✓

---

## Task 2: Header — wordmark, token pill, ghost clear button

**Files:**
- Modify: `app/static/index.html` — update `<header>` markup and add header-scoped CSS. Update `updateTokenIndicator()` in the script to write the new pill structure.

- [ ] **Step 1: Add header CSS**

Append inside `<style>` (anywhere after the base rules):

```css
.wordmark {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.wordmark .logo {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  background: var(--accent);
}
.wordmark .sep { color: var(--text-mute); font-weight: 400; margin: 0 2px; }
.wordmark .sub { color: var(--text-dim); font-weight: 400; }

.header-right { display: flex; align-items: center; gap: 12px; }

.token-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-dim);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 12px;
  font-variant-numeric: tabular-nums;
}
.token-pill .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-mute);
}
.token-pill.set .dot { background: var(--success); }
.token-pill.set { color: var(--text); }
```

- [ ] **Step 2: Replace header markup**

Replace the current `<header>…</header>` block with:

```html
<header>
  <div class="wordmark">
    <span class="logo" aria-hidden="true"></span>
    <span>FLUX</span>
    <span class="sep">·</span>
    <span class="sub">Image Generator</span>
  </div>
  <div class="header-right">
    <span id="token-indicator" class="token-pill"><span class="dot"></span><span class="label">token not set</span></span>
    <button id="clear-token-btn" type="button" class="ghost-btn">Clear</button>
  </div>
</header>
```

- [ ] **Step 3: Update `updateTokenIndicator()`**

Find the existing `updateTokenIndicator` function in the `<script>` and replace it with:

```js
function updateTokenIndicator() {
  const el = document.getElementById("token-indicator");
  const label = el.querySelector(".label");
  if (getToken()) {
    el.classList.add("set");
    label.textContent = "token set";
  } else {
    el.classList.remove("set");
    label.textContent = "token not set";
  }
}
```

- [ ] **Step 4: Reload and verify**

Reload http://localhost:8000. Expected:
- Header shows a small indigo square, then `FLUX · Image Generator`.
- Right side: pill showing `token set` with a small green dot (if token was previously saved) or `token not set` with a muted dot.
- "Clear" button is a ghost-style outlined button. Clicking it empties the token and flips the pill to the muted state (and reopens the modal — modal itself is still the ugly old one; that's Task 7).

---

## Task 3: History panel — label row, 2-column thumbnail grid, empty + selected states

**Files:**
- Modify: `app/static/index.html` — update `<aside id="history-pane">` markup, add history CSS, update `renderHistory()` in the script to emit the new structure and track a selected entry.

- [ ] **Step 1: Add history CSS**

Append inside `<style>`:

```css
#history-pane .history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px 12px 4px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 12px;
}
#history-pane .history-head .count { font-size: 12px; color: var(--text-dim); }
#history-pane .history-head .left { display: flex; align-items: baseline; gap: 10px; }

#history-list {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
}

.history-empty {
  color: var(--text-mute);
  font-size: 12px;
  text-align: center;
  padding: 24px 8px;
}

.history-item {
  position: relative;
  aspect-ratio: 1 / 1;
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--surface-2);
  cursor: pointer;
  transition: transform 120ms;
}
.history-item:hover { transform: scale(1.03); }
.history-item.selected { box-shadow: 0 0 0 2px var(--accent); }
.history-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.history-item .dur-chip {
  position: absolute;
  bottom: 4px;
  right: 4px;
  background: #00000099;
  color: #fff;
  font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  font-size: 11px;
  border-radius: 4px;
  padding: 1px 5px;
  pointer-events: none;
}
```

- [ ] **Step 2: Replace history markup**

Replace the current `<aside id="history-pane">…</aside>` block with:

```html
<aside id="history-pane">
  <div class="history-head">
    <div class="left">
      <div class="section-label" style="margin:0">History</div>
      <span class="count" id="history-count">0 items</span>
    </div>
    <button id="clear-history-btn" type="button" class="ghost-btn">Clear</button>
  </div>
  <div id="history-list"></div>
</aside>
```

- [ ] **Step 3: Track selected entry + update `renderHistory()`**

Near the top of the `<script>`, add a module-scoped variable:

```js
let selectedTaskId = null;
```

Replace the existing `renderHistory` function with:

```js
function renderHistory() {
  const list = document.getElementById("history-list");
  const count = document.getElementById("history-count");
  const entries = readHistory();
  list.innerHTML = "";
  count.textContent = `${entries.length} item${entries.length === 1 ? "" : "s"}`;
  if (entries.length === 0) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "No images yet";
    list.appendChild(empty);
    return;
  }
  for (const entry of entries) {
    const item = document.createElement("div");
    item.className = "history-item" + (entry.task_id === selectedTaskId ? " selected" : "");
    item.title = `${entry.kind}: ${entry.prompt || ""}`;
    const img = document.createElement("img");
    img.src = entry.thumbnail;
    item.appendChild(img);
    if (typeof entry.duration_ms === "number") {
      const chip = document.createElement("div");
      chip.className = "dur-chip";
      chip.textContent = formatDuration(entry.duration_ms);
      item.appendChild(chip);
    }
    item.addEventListener("click", () => {
      selectedTaskId = entry.task_id;
      showHistoryEntry(entry);
      renderHistory();
    });
    list.appendChild(item);
  }
}
```

- [ ] **Step 4: Add `formatDuration` helper**

Add near the top of the `<script>` (e.g., right below the constants):

```js
function formatDuration(ms) {
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}
```

- [ ] **Step 5: Reload and verify**

Reload. Expected:
- "HISTORY" uppercase label + `N items` count on the same row, `Clear` ghost button right-aligned.
- 2-column grid of thumbnails with rounded corners, hover scales slightly.
- If history is empty, centered muted "No images yet".
- Clicking a thumbnail highlights it with a 2px indigo ring.
- Thumbnails from BEFORE this change do not show a duration chip (chip appears only for new generations after Task 6 is complete — that's fine).

---

## Task 4: Image stage — empty, loading, done states (skeleton, no timer yet)

This task lays out all three visual states and wires up the state switch. The live timer lands in Task 6.

**Files:**
- Modify: `app/static/index.html` — replace `<main>…</main>` contents with new stage markup, add stage CSS, update the submit handler and `showHistoryEntry` to set `data-state` and fill the meta bar.

- [ ] **Step 1: Add stage CSS**

Append inside `<style>`:

```css
.stage-box {
  width: min(100%, 900px);
  aspect-ratio: 1 / 1;
  max-height: calc(100vh - 200px);
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
}
#stage[data-state="empty"] .stage-box,
#stage[data-state="loading"] .stage-box {
  border: 2px dashed var(--border);
  background: transparent;
}
#stage[data-state="loading"] .stage-box {
  background:
    linear-gradient(90deg, var(--surface) 0%, var(--surface-2) 50%, var(--surface) 100%);
  background-size: 200% 100%;
  animation: skeleton 1.6s linear infinite;
}
@keyframes skeleton { from { background-position: 200% 0; } to { background-position: -200% 0; } }

#stage[data-state="empty"] .empty-content,
#stage[data-state="loading"] .loading-content { display: flex; flex-direction: column; align-items: center; gap: 12px; }
#stage[data-state="empty"] .loading-content,
#stage[data-state="empty"] .done-content,
#stage[data-state="loading"] .empty-content,
#stage[data-state="loading"] .done-content,
#stage[data-state="done"] .empty-content,
#stage[data-state="done"] .loading-content { display: none; }

#stage[data-state="done"] .stage-box { border: none; background: transparent; }
#stage[data-state="done"] #result-image {
  max-width: 100%;
  max-height: calc(100vh - 200px);
  object-fit: contain;
  border-radius: var(--radius);
  box-shadow: 0 8px 32px #0006;
  display: block;
}

.spinner {
  width: 28px; height: 28px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 800ms linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.stage-empty-icon { width: 48px; height: 48px; color: var(--text-mute); }

.meta-bar {
  width: min(100%, 900px);
  margin-top: 16px;
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 16px;
  min-height: 40px;
  font-size: 13px;
}
.meta-bar .prompt-excerpt {
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta-bar .params-summary {
  color: var(--text-dim);
  font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  font-size: 12px;
  white-space: nowrap;
}
.meta-bar .actions { display: flex; gap: 8px; }
.meta-bar a, .meta-bar button {
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-dim);
  padding: 4px 10px;
  font-size: 12px;
  text-decoration: none;
  cursor: pointer;
}
.meta-bar a:hover, .meta-bar button:hover { color: var(--text); border-color: var(--text-dim); background: var(--surface-2); }

#stage[data-state="done"] .meta-bar { display: grid; }
#stage[data-state="empty"] .meta-bar,
#stage[data-state="loading"] .meta-bar { display: none; }
```

- [ ] **Step 2: Replace `<main>` markup**

Replace the contents of `<main>…</main>` with:

```html
<main id="stage" data-state="empty">
  <div class="stage-box">
    <div class="empty-content">
      <svg class="stage-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <circle cx="8.5" cy="8.5" r="1.5"/>
        <path d="M21 15l-5-5L5 21"/>
      </svg>
      <div>Your image will appear here</div>
    </div>
    <div class="loading-content">
      <div class="spinner" aria-hidden="true"></div>
      <div id="stage-loading-label" class="mono" style="font-size:12px;color:var(--text-dim)">starting…</div>
    </div>
    <img id="result-image" alt="generated image" />
  </div>
  <div class="meta-bar">
    <div class="prompt-excerpt" id="meta-prompt"></div>
    <div class="params-summary" id="meta-params"></div>
    <div class="actions">
      <a id="download-link" download>Download</a>
      <button id="rerun-btn" type="button">Re-run</button>
    </div>
  </div>
</main>
```

Note: the form, status line, mode toggle, and result-actions are no longer children of `<main>`. The form will live in `<section id="controls">` after Task 5. For now, temporarily move them into `<section id="controls">` so the page still works end-to-end:

Inside `<section id="controls">`, replace the "controls go here" placeholder with the existing (unstyled) form markup from the old `<main>` — the `<div class="mode-toggle">`, `<form id="gen-form">`, and the old status line. Task 5 will restyle these. The result img / download / rerun are no longer needed inside `<section id="controls">` because they moved to `<main>`.

- [ ] **Step 3: Update the submit handler — remove `resultActions` and drive `#stage` state**

At the top of `<script>`, the existing file has:
```js
const resultImg = document.getElementById("result-image");
const resultActions = document.getElementById("result-actions");
const downloadLink = document.getElementById("download-link");
```
Delete the `resultActions` line. The `#result-actions` element no longer exists; all references to `resultActions.classList.*` below must also be removed.

Replace the body of `form.addEventListener("submit", async (e) => { ... })` with:

```js
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!getToken()) { showTokenModal(); return; }
  const submitBtn = document.getElementById("generate-btn");
  if (submitBtn.disabled) return;
  submitBtn.disabled = true;

  const stage = document.getElementById("stage");
  stage.dataset.state = "loading";
  document.getElementById("stage-loading-label").textContent = "submitting…";
  statusLine.textContent = "submitting…";

  try {
    let body = formValues();
    let path = "/tasks/txt2img";
    if (mode === "img2img") {
      const file = form.elements["init_image_file"].files[0];
      if (!file) throw new Error("select an image file");
      body.init_image = await fileToBase64(file);
      path = "/tasks/img2img";
    }
    const submitted = await apiPost(path, body);
    const done = await pollUntilDone(submitted.task_id);

    const imgRes = await apiGet(done.image_url);
    const blob = await imgRes.blob();
    const url = URL.createObjectURL(blob);
    revokeIfBlob(resultImg.src);
    resultImg.src = url;
    downloadLink.href = url;
    downloadLink.download = `${submitted.task_id}.png`;

    stage.dataset.state = "done";
    document.getElementById("meta-prompt").textContent = body.prompt || "";
    document.getElementById("meta-params").textContent = formatParams(body, done);
    statusLine.textContent = "done";

    if (window.__fluxAddHistory) {
      await window.__fluxAddHistory({
        task_id: submitted.task_id,
        kind: mode,
        prompt: body.prompt,
        params: body,
        blob,
        created_at: new Date().toISOString(),
      });
    }
  } catch (err) {
    statusLine.textContent = "error: " + err.message;
    stage.dataset.state = resultImg.naturalWidth > 0 ? "done" : "empty";
  } finally {
    submitBtn.disabled = false;
  }
});
```

Add this helper function near `formatDuration`:

```js
function formatParams(body, taskDetail) {
  const parts = [];
  if (body.width && body.height) {
    parts.push(body.width === body.height ? `${body.width}²` : `${body.width}×${body.height}`);
  }
  if (body.num_inference_steps != null) parts.push(`${body.num_inference_steps} steps`);
  if (body.seed != null) parts.push(`seed ${body.seed}`);
  if (taskDetail && taskDetail.started_at && taskDetail.finished_at) {
    const ms = Date.parse(taskDetail.finished_at) - Date.parse(taskDetail.started_at);
    parts.push(formatDuration(ms));
  }
  return parts.join(" · ");
}
```

(Note: `statusLine`, the old inline `#status-line` element, still exists inside `<section id="controls">` after the Task 4 Step 2 temp move. Task 5 replaces it with the new styled status line; Task 6 swaps the `statusLine.textContent = …` calls for `setStatus(kind, text)`.)

- [ ] **Step 4: Rewrite `showHistoryEntry` to drive stage state**

Replace the entire `showHistoryEntry` function body with:

```js
async function showHistoryEntry(entry) {
  form.elements["prompt"].value = entry.prompt || "";
  if (entry.params) {
    for (const key of ["width", "height", "num_inference_steps", "seed", "strength"]) {
      if (entry.params[key] !== undefined && form.elements[key]) {
        form.elements[key].value = entry.params[key];
      }
    }
  }
  document.querySelectorAll(".mode-toggle button").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === entry.kind));
  mode = entry.kind;
  document.getElementById("img2img-fields").classList.toggle("hidden", mode !== "img2img");

  const stage = document.getElementById("stage");
  stage.dataset.state = "loading";
  document.getElementById("stage-loading-label").textContent = "loading from history…";
  statusLine.textContent = "loading…";

  try {
    const r = await apiGet(`/tasks/${entry.task_id}/image`);
    if (r.ok) {
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      revokeIfBlob(resultImg.src);
      resultImg.src = url;
      downloadLink.href = url;
      downloadLink.download = `${entry.task_id}.png`;
      statusLine.textContent = "restored from server";
    } else {
      revokeIfBlob(resultImg.src);
      resultImg.src = entry.thumbnail;
      downloadLink.removeAttribute("href");
      statusLine.textContent = "thumbnail only";
    }
  } catch (e) {
    revokeIfBlob(resultImg.src);
    resultImg.src = entry.thumbnail;
    statusLine.textContent = "thumbnail only";
  }

  stage.dataset.state = "done";
  document.getElementById("meta-prompt").textContent = entry.prompt || "";
  document.getElementById("meta-params").textContent = formatParams(entry.params || {}, {
    started_at: entry.started_at,
    finished_at: entry.finished_at,
  });
}
```

Note the removed `resultImg.classList.remove("hidden")` and `resultActions.classList.remove("hidden")` lines — the stage state drives visibility via CSS now. `entry.started_at` and `entry.finished_at` will be `undefined` for pre-Task-6 history entries; `formatParams` already guards that case, so the meta bar will simply omit the duration for old entries.

- [ ] **Step 5: Reload and verify**

Reload. Expected:
- On fresh load: dashed empty box centered in `<main>`, with image icon and "Your image will appear here".
- Submit a prompt: dashed box animates as a shimmering skeleton, spinner + "submitting…" label inside.
- On completion: the image appears in place, meta bar below shows prompt excerpt, params summary (e.g., `1024² · 4 steps · 6.2s`), Download link, Re-run button.
- Clicking a history entry shows the loading shimmer briefly, then the restored image + meta bar.
- Form submission still works end to end.

---

## Task 5: Control panel — mode segmented control, prompt, params, dice button, img2img extras

**Files:**
- Modify: `app/static/index.html` — replace the temporary form markup inside `<section id="controls">` with the redesigned structured markup; add controls CSS; wire up dice button and segmented control.

- [ ] **Step 1: Add controls CSS**

Append inside `<style>`:

```css
.segmented {
  display: grid;
  grid-template-columns: 1fr 1fr;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 3px;
  gap: 2px;
}
.segmented button {
  border: none;
  background: transparent;
  color: var(--text-dim);
  padding: 7px 10px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 999px;
  transition: background 120ms, color 120ms;
}
.segmented button.active { background: var(--accent); color: #fff; }
.segmented button:not(.active):hover { color: var(--text); }

.field-group { display: flex; flex-direction: column; gap: 6px; }
.field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

.hint {
  font-size: 11px;
  color: var(--text-mute);
  margin-top: 2px;
}

.seed-wrap { position: relative; }
.seed-wrap input { padding-right: 34px; font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace; }
.seed-wrap .dice-btn {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: var(--text-dim);
  border-radius: var(--radius-sm);
}
.seed-wrap .dice-btn:hover { color: var(--text); background: var(--surface); }

.dropzone {
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  padding: 12px;
  text-align: center;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 120ms, color 120ms;
}
.dropzone:hover, .dropzone.drag { border-color: var(--accent); color: var(--text); }
.dropzone .preview {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-start;
  text-align: left;
}
.dropzone .preview img {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: var(--radius-sm);
}

input[type="range"] {
  -webkit-appearance: none;
  width: 100%;
  background: transparent;
}
input[type="range"]::-webkit-slider-runnable-track {
  height: 4px;
  background: var(--surface-2);
  border-radius: 2px;
}
input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--accent);
  margin-top: -6px;
  border: none;
}
input[type="range"]::-moz-range-track { height: 4px; background: var(--surface-2); border-radius: 2px; }
input[type="range"]::-moz-range-thumb { width: 16px; height: 16px; border: none; border-radius: 50%; background: var(--accent); }

#generate-btn {
  width: 100%;
  height: 40px;
  background: var(--accent);
  border: none;
  border-radius: var(--radius-sm);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: background 120ms;
}
#generate-btn:hover:not(:disabled) { background: var(--accent-hover); }
#generate-btn:disabled { background: var(--surface-2); color: var(--text-mute); cursor: not-allowed; }
#generate-btn .shortcut { font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace; font-size: 11px; opacity: 0.7; }

#status-line {
  font-size: 12px;
  font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  color: var(--text-dim);
  min-height: 16px;
}
#status-line.running { color: var(--text); }
#status-line.error { color: var(--danger); }
#status-line.success { color: var(--success); }
#status-line .dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  margin-right: 6px;
  vertical-align: middle;
  animation: pulse 1.2s ease-in-out infinite;
}
#status-line:not(.running) .dot { display: none; }
@keyframes pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
```

- [ ] **Step 2: Replace `<section id="controls">` markup**

Replace the contents of `<section id="controls">` entirely with:

```html
<section id="controls">
  <div class="field-group">
    <div class="section-label">Mode</div>
    <div class="segmented mode-toggle">
      <button type="button" data-mode="txt2img" class="active">Text → Image</button>
      <button type="button" data-mode="img2img">Image → Image</button>
    </div>
  </div>

  <form id="gen-form">
    <div class="field-group">
      <label for="prompt-input" class="section-label">Prompt</label>
      <textarea id="prompt-input" name="prompt" rows="4" required placeholder="describe the image…"></textarea>
    </div>

    <div class="field-group" style="margin-top:16px">
      <div class="section-label">Dimensions</div>
      <div class="field-row">
        <div>
          <input name="width" type="number" value="1024" step="64" min="256" max="1536" class="mono" />
        </div>
        <div>
          <input name="height" type="number" value="1024" step="64" min="256" max="1536" class="mono" />
        </div>
      </div>
      <div class="hint">min 256 · max 1536 · step 64</div>
    </div>

    <div class="field-group" style="margin-top:16px">
      <div class="section-label">Generation</div>
      <div class="field-row">
        <div>
          <input name="num_inference_steps" type="number" value="4" min="1" max="8" class="mono" />
        </div>
        <div class="seed-wrap">
          <input name="seed" type="number" placeholder="random" class="mono" />
          <button type="button" class="dice-btn" id="dice-btn" title="random seed" aria-label="random seed">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
              <rect x="3" y="3" width="18" height="18" rx="3"/>
              <circle cx="8" cy="8" r="1.4" fill="currentColor"/>
              <circle cx="16" cy="16" r="1.4" fill="currentColor"/>
              <circle cx="16" cy="8" r="1.4" fill="currentColor"/>
              <circle cx="8" cy="16" r="1.4" fill="currentColor"/>
            </svg>
          </button>
        </div>
      </div>
      <div class="hint">steps 1–8 · schnell sweet spot: 4</div>
    </div>

    <div id="img2img-fields" class="field-group hidden" style="margin-top:16px">
      <div class="section-label">Init image</div>
      <label class="dropzone" id="dropzone">
        <span class="dz-label">Click or drop image</span>
        <input name="init_image_file" type="file" accept="image/png,image/jpeg" class="hidden" />
      </label>
      <div class="section-label" style="margin-top:12px">Strength</div>
      <div class="field-row" style="grid-template-columns: 1fr 48px; align-items:center">
        <input name="strength" type="range" value="0.7" step="0.05" min="0" max="1" />
        <span id="strength-value" class="mono" style="text-align:right;color:var(--text-dim);font-size:12px">0.70</span>
      </div>
    </div>

    <button id="generate-btn" type="submit" style="margin-top:20px">
      Generate
      <span class="shortcut">⌘↵</span>
    </button>
    <div id="status-line" style="margin-top:10px"></div>
  </form>
</section>
```

Delete any leftover old `.mode-toggle`, `<form>`, or `#status-line` markup that was temporarily parked in `<section id="controls">` during Task 4. The `<main>` block should still contain the stage + meta bar unchanged.

- [ ] **Step 3: Wire up the dice button**

In the `<script>`, add after the existing DOM wiring:

```js
document.getElementById("dice-btn").addEventListener("click", () => {
  const el = document.querySelector('input[name="seed"]');
  el.value = Math.floor(Math.random() * 2_147_483_647);
});
```

- [ ] **Step 4: Wire up the dropzone and strength display**

Add:

```js
const dropzone = document.getElementById("dropzone");
const fileInput = document.querySelector('input[name="init_image_file"]');
if (dropzone && fileInput) {
  dropzone.addEventListener("click", (e) => {
    // let the native label -> input click happen; no-op needed
  });
  fileInput.addEventListener("change", () => renderDropzone());
  ["dragenter", "dragover"].forEach(ev => dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach(ev => dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag");
  }));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
      const dt = new DataTransfer();
      dt.items.add(e.dataTransfer.files[0]);
      fileInput.files = dt.files;
      renderDropzone();
    }
  });
}

function renderDropzone() {
  const f = fileInput.files[0];
  const label = dropzone.querySelector(".dz-label");
  const existingPreview = dropzone.querySelector(".preview");
  if (existingPreview) existingPreview.remove();
  if (!f) { label.textContent = "Click or drop image"; label.style.display = ""; return; }
  label.style.display = "none";
  const preview = document.createElement("div");
  preview.className = "preview";
  const img = document.createElement("img");
  img.src = URL.createObjectURL(f);
  const name = document.createElement("span");
  name.textContent = f.name;
  name.style.fontSize = "12px";
  preview.appendChild(img);
  preview.appendChild(name);
  dropzone.appendChild(preview);
}

const strengthInput = document.querySelector('input[name="strength"]');
const strengthValue = document.getElementById("strength-value");
if (strengthInput && strengthValue) {
  const sync = () => strengthValue.textContent = Number(strengthInput.value).toFixed(2);
  strengthInput.addEventListener("input", sync);
  sync();
}
```

- [ ] **Step 5: Reload and verify**

Reload. Expected:
- Right column: Mode segmented pill control at top (indigo active).
- Prompt textarea with placeholder.
- "DIMENSIONS" group (W/H inputs), hint line below.
- "GENERATION" group (Steps/Seed), dice button inside the Seed input; clicking it fills a random int.
- Switching mode to "Image → Image" reveals the Init image group: dropzone responds to drag+drop and shows a preview.
- Strength slider numeric display updates in real time.
- Generate button is full-width indigo with "Generate ⌘↵" label.
- Submitting still works end to end (fake pipeline).

---

## Task 6: Live elapsed-time timer + duration_ms in history

**Files:**
- Modify: `app/static/index.html` — add timer state to the submit handler, update the status line per-state, persist `duration_ms` in history.

- [ ] **Step 1: Add timer helpers**

Near the top of `<script>`, add:

```js
let stageTimer = null;
let stageTimerStart = 0;

function startStageTimer() {
  stageTimerStart = performance.now();
  stopStageTimer();
  stageTimer = setInterval(() => {
    const elapsed = Math.floor((performance.now() - stageTimerStart) / 1000);
    const mm = Math.floor(elapsed / 60).toString().padStart(2, "0");
    const ss = (elapsed % 60).toString().padStart(2, "0");
    setStatus("running", `running · ${mm}:${ss}`);
    const label = document.getElementById("stage-loading-label");
    if (label) label.textContent = `${mm}:${ss}`;
  }, 500);
}
function stopStageTimer() {
  if (stageTimer) { clearInterval(stageTimer); stageTimer = null; }
}

function setStatus(kind, text) {
  const el = document.getElementById("status-line");
  el.classList.remove("running", "error", "success");
  if (kind) el.classList.add(kind);
  if (kind === "running") {
    el.innerHTML = `<span class="dot"></span>${text}`;
  } else {
    el.textContent = text || "";
  }
}
```

- [ ] **Step 2: Update the submit handler to use the timer and setStatus**

Find the submit handler. Replace every `statusLine.textContent = "..."` assignment with the appropriate `setStatus(kind, text)` call:

- At start: `setStatus(null, "submitting…");` (after `submitBtn.disabled = true;`)
- Do NOT start the timer yet — it starts when the task first becomes `running`.

In `pollUntilDone`, replace the loop body so it starts the timer once and keeps the status in sync:

```js
async function pollUntilDone(taskId) {
  let timerStarted = false;
  while (true) {
    const r = await apiGet(`/tasks/${taskId}`);
    if (!r.ok) throw new Error(`status ${r.status}`);
    const body = await r.json();
    if (body.status === "done") return body;
    if (body.status === "failed") throw new Error(body.error || "task failed");
    if (body.status === "running" && !timerStarted) {
      startStageTimer();
      timerStarted = true;
    }
    if (!timerStarted) {
      const pos = body.queue_position ? ` · queue pos ${body.queue_position}` : "";
      setStatus(null, `${body.status}${pos}`);
    }
    await new Promise(r => setTimeout(r, 1000));
  }
}
```

On successful completion (after setting the image src and meta bar), replace the existing status with:

```js
stopStageTimer();
const finalMs = Date.parse(done.finished_at) - Date.parse(done.started_at);
setStatus("success", `done in ${formatDuration(finalMs)}`);
```

On error:

```js
stopStageTimer();
setStatus("error", "error: " + err.message);
```

Also update `showHistoryEntry` (written in Task 4 Step 4) to use `setStatus` instead of `statusLine.textContent = …`. Replace each of the three assignments:
- `statusLine.textContent = "loading…";` → `setStatus(null, "loading…");`
- `statusLine.textContent = "restored from server";` → `setStatus(null, "restored from server");`
- `statusLine.textContent = "thumbnail only";` (×2 occurrences) → `setStatus(null, "thumbnail only");`

- [ ] **Step 3: Persist duration_ms in history**

Find the `window.__fluxAddHistory` call in the submit handler. Update the call to include `duration_ms`:

```js
if (window.__fluxAddHistory) {
  await window.__fluxAddHistory({
    task_id: submitted.task_id,
    kind: mode,
    prompt: body.prompt,
    params: body,
    blob,
    created_at: new Date().toISOString(),
    started_at: done.started_at,
    finished_at: done.finished_at,
    duration_ms: Date.parse(done.finished_at) - Date.parse(done.started_at),
  });
}
```

Update the `window.__fluxAddHistory` function definition to pass these fields through:

```js
window.__fluxAddHistory = async function (entry) {
  const { blob, ...meta } = entry;
  const thumbnail = await makeThumbnail(blob);
  if (meta.params && meta.params.init_image) delete meta.params.init_image;
  const stored = { ...meta, thumbnail };
  const arr = readHistory();
  arr.unshift(stored);
  while (arr.length > HISTORY_CAP) arr.pop();
  writeHistory(arr);
  renderHistory();
};
```

(`duration_ms`, `started_at`, and `finished_at` flow through because `...meta` preserves them.)

- [ ] **Step 4: Reload and verify**

Reload. Hard-refresh to wipe any cached JS. Expected:
- Submit a prompt. Status line shows `submitting…`, then `running · 00:01`, ticking with a pulsing indigo dot.
- The loading skeleton in `<main>` shows the same `00:01` ticking below the spinner.
- On completion: status line turns green and reads `done in 0.8s` (or similar).
- The new history thumbnail shows a small monospace chip in its bottom-right with the duration.
- Selecting a history thumbnail restores the image with its duration displayed in the meta bar (`1024² · 4 steps · seed … · 0.8s`).
- Old history entries (from before this task) render without a chip — this is expected.

---

## Task 7: Token modal restyle + Esc close + ⌘↵ shortcut

**Files:**
- Modify: `app/static/index.html` — restyle the token modal, wire `Esc` to close, wire `⌘/Ctrl + Enter` to submit the form from any input.

- [ ] **Step 1: Add modal CSS**

Append inside `<style>`:

```css
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: #0b0b0dcc;
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  width: 420px;
  max-width: 92vw;
  box-shadow: 0 20px 60px #0008;
}
.modal h3 { margin: 0 0 8px 0; font-size: 16px; font-weight: 600; }
.modal p { margin: 0 0 16px 0; font-size: 13px; color: var(--text-dim); }
.modal .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.modal .save-btn {
  background: var(--accent);
  border: none;
  border-radius: var(--radius-sm);
  color: #fff;
  font-weight: 600;
  padding: 8px 16px;
  font-size: 13px;
}
.modal .save-btn:hover { background: var(--accent-hover); }
```

- [ ] **Step 2: Replace modal markup**

Replace the existing `<div id="token-modal">…</div>` block with:

```html
<div id="token-modal" class="modal-backdrop hidden" role="dialog" aria-modal="true" aria-labelledby="token-title">
  <div class="modal">
    <h3 id="token-title">Enter API token</h3>
    <p>The token is printed in the Colab log at startup. It is stored in your browser only.</p>
    <input id="token-input" type="password" placeholder="paste token here" />
    <div class="actions">
      <button id="token-save" type="button" class="save-btn">Save</button>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Wire Esc and ⌘↵ shortcuts**

Append to `<script>`:

```js
document.addEventListener("keydown", (e) => {
  // Esc: close token modal
  if (e.key === "Escape") {
    const modal = document.getElementById("token-modal");
    if (!modal.classList.contains("hidden")) hideTokenModal();
  }
  // Cmd/Ctrl + Enter: submit the form
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    const form = document.getElementById("gen-form");
    if (form && !document.getElementById("generate-btn").disabled) {
      e.preventDefault();
      form.requestSubmit();
    }
  }
});
```

- [ ] **Step 4: Reload and verify**

Reload. Expected:
- Click "Clear" in header to open the modal. Backdrop is blurred. Modal is dark with indigo Save button.
- Press Esc: modal closes.
- Re-open, paste `dev`, click Save: closes, token pill turns green.
- Click into the Prompt textarea and press `⌘+Enter` (macOS) or `Ctrl+Enter`: form submits.

---

## Task 8: Final polish pass and manual QA

No code changes expected unless a bug surfaces. Just walk the spec §12 checklist and fix regressions inline.

- [ ] **Step 1: Manual QA — happy path**

1. Hard-reload http://localhost:8000.
2. Without a token, modal appears over blurred background. Press Esc — modal closes; reopen by clicking Clear. Paste `dev`, Save.
3. Empty state visible in `<main>`.
4. Type a prompt, press `⌘/Ctrl+Enter`. Expected: status goes `submitting… → running · 00:01… → done in 0.7s`. Image appears with meta bar below.
5. Click the 🎲 dice button: Seed input fills with a random int.
6. Change Steps to 6, re-run. Duration goes up, reflected in status, meta bar, and new history chip.
7. Switch to "Image → Image" mode. Drop any image on the dropzone; preview thumbnail shows. Drag the Strength slider; numeric readout updates live. Submit.

- [ ] **Step 2: Manual QA — history + edge cases**

1. Click an old history thumbnail (no chip). The stage shows loading, then restores. Meta bar shows params WITHOUT a duration (because those entries have no `duration_ms`).
2. Click a new history thumbnail (with chip). Meta bar shows duration.
3. Clear history. Empty state "No images yet" appears in the history panel.
4. Force an error (e.g., submit with an invalid/cleared token): status line goes red with `error: …`; stage reverts to empty or previous done state cleanly (no frozen spinner).
5. Test widths: resize browser to 1280, 1440, 1920. Layout should hold; image stage never squeezes below ~500px wide with the default 240+340 side columns.

- [ ] **Step 3: Final sanity**

- Run any existing backend tests to confirm no regression:
  ```bash
  pytest -q
  ```
- Load time is fine (single file, no extra network).
- No JS errors in the console on any flow.

---

## Rollback

If the redesign needs to be reverted, the only file changed is `app/static/index.html`. Restore it from any prior copy (Colab cache, editor history, or the initial version in this repo). No backend state or API contract was altered.
