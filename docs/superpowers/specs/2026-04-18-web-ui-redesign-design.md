# Web UI Redesign — Design Spec

**Date:** 2026-04-18
**Scope:** Rewrite of `app/static/index.html` (markup + inline CSS + inline JS).
**Out of scope:** Backend (`app/routes.py`, `app/store.py`, etc.) — already exposes everything needed.

## 1. Motivation

The current single-file UI (`app/static/index.html`) has several usability problems visible at a glance:

- Large empty band between the header and the rest of the page — wasted vertical space.
- Generated image has no dedicated display area; the `#result` block lives under the form and gets pushed around by content above it.
- History panel is a narrow left sidebar that is mostly empty; thumbnails are single-column and cramped.
- The `Generate` button is small and visually weak.
- No feedback on how long a render took, which matters for a tool whose selling point is "4-step schnell is fast."
- Light/dark mode is left to the OS via `color-scheme`, giving an inconsistent look and no control over contrast.

## 2. Goals

1. Give the generated image a **permanent, dominant stage** in the layout.
2. Make the "generate → look → tweak → regenerate" loop fast, since that is the primary use pattern with schnell.
3. Surface render duration prominently so the user feels the speed.
4. Apply a coherent dark visual language that keeps the UI quiet and lets the generated image carry the color.

## 3. Non-Goals

- No build step, no framework, no dependencies. Stays as a single `index.html` with inline CSS and vanilla JS.
- No backend changes. Duration is computed client-side from `started_at` / `finished_at`.
- No responsive mobile layout. Tool is designed for desktop (Colab workflow).
- No new API calls, new endpoints, or new history schema (other than one additive field).

## 4. Layout

Three-column fixed grid, full viewport height:

```
┌─────────────────────────────────────────────────────────────────┐
│  FLUX · Image Generator              ● token set    [Clear]     │  48px header
├──────────┬──────────────────────────────────────┬───────────────┤
│ HISTORY  │                                      │  MODE         │
│ 12 items │                                      │  ┌───┬───┐    │
│ [clear]  │                                      │  │T→I│I→I│    │
│          │                                      │  └───┴───┘    │
│ [□][□]   │         ┌──────────────┐             │               │
│ [□][□]   │         │              │             │  PROMPT       │
│ [□][□]   │         │   image      │             │  ┌─────────┐  │
│ [□][□]   │         │              │             │  │         │  │
│ ...      │         └──────────────┘             │  └─────────┘  │
│          │                                      │               │
│          │  prompt excerpt · 1024² · 4 · 6.2s   │  W     H      │
│          │  [Download] [Re-run]                 │  1024  1024   │
│          │                                      │  Steps  Seed  │
│          │                                      │  4      🎲    │
│          │                                      │               │
│          │                                      │  [ Generate ] │
│          │                                      │  status line  │
│  240px   │              flex                    │    340px      │
└──────────┴──────────────────────────────────────┴───────────────┘
```

- **Header:** 48px tall, full width, `border-bottom: 1px`. Left: wordmark (4×4 indigo square glyph + "FLUX · Image Generator"). Right: token state pill + ghost `Clear` button.
- **Left — History panel:** 240px wide, `border-right: 1px`, vertical scroll. Section label "HISTORY" in 11px uppercase, item count and ghost clear button on the same row. 2-column thumbnail grid.
- **Center — Image stage:** flexible width (fills remaining space). Padding 32px. Content centered both axes. Houses the empty / loading / done states.
- **Right — Control panel:** 340px wide, `border-left: 1px`, vertical scroll. Mode toggle at top, then prompt, then grouped parameters, then Generate, then status line.

## 5. Color system

CSS custom properties declared on `:root`:

| Token | Value | Purpose |
|---|---|---|
| `--bg` | `#141416` | App background |
| `--surface` | `#1c1c21` | Panel base (history, control) |
| `--surface-2` | `#25252c` | Inputs, hovered rows |
| `--border` | `#2d2d35` | Dividers, input borders |
| `--text` | `#e8e8ec` | Primary text |
| `--text-dim` | `#8a8a93` | Labels, meta |
| `--text-mute` | `#5c5c66` | Placeholders |
| `--accent` | `#8b7dd8` | Buttons, selection, focus rings |
| `--accent-hover` | `#a195e8` | Hover state |
| `--accent-dim` | `#8b7dd822` | Focus ring halo, selected bg |
| `--danger` | `#c9506a` | Error status |
| `--success` | `#7dd89e` | Token-set indicator dot |

Light mode is **not** supported in this rewrite. The `color-scheme: light dark` declaration is removed.

## 6. Typography

- UI: `Inter, system-ui, -apple-system, sans-serif`, base 14px, line-height 1.45.
- Numeric/technical: `ui-monospace, "JetBrains Mono", Menlo, monospace` — applied to seed inputs, task IDs, duration strings.
- Scale:
  - 20px / 600 — page wordmark
  - 14px / 400 — body, inputs
  - 13px / 500 — buttons, segmented control
  - 11px / 600 / uppercase / 0.08em tracking — section labels ("HISTORY", "PROMPT", "DIMENSIONS", "GENERATION")
  - 12px / 400 — meta, status, hint text

## 7. Component detail

### 7.1 Header (`<header>`)

- 48px fixed height.
- Left cluster: 16×16 rounded-3 indigo square (using `--accent`) + text `FLUX` (600) + middle-dot separator + `Image Generator` (400, `--text-dim`).
- Right cluster:
  - Token pill: 8px dot (green `--success` when set, `--text-mute` when not) + text `token set` / `token not set`.
  - Ghost button `Clear` — 12px, `--text-dim`, hover `--text`.

### 7.2 History panel (`<aside>`)

- Header row: `HISTORY` label + `<N> items` in `--text-dim` + ghost `clear` button.
- Thumbnail grid: `grid-template-columns: repeat(2, 1fr)`, 6px gap, 8px padding.
- Each thumbnail:
  - 1:1 aspect, `border-radius: 8px`, `object-fit: cover`.
  - Bottom-right chip overlay shows duration: `background: #00000099`, `color: #fff`, `font: 11px ui-monospace`, `border-radius: 4px`, `padding: 1px 5px`, `bottom: 4px; right: 4px`. Chip is only rendered if `duration_ms` is present in the history entry.
  - Hover: `transform: scale(1.03)`, `transition: 120ms`.
  - Selected (i.e., the history entry currently shown in the stage): 2px `--accent` ring via `box-shadow: 0 0 0 2px var(--accent)`.
- Empty state: centered `--text-mute` text "No images yet" at 12px.

### 7.3 Image stage (`<main>`)

Three visual states, switched by a single `data-state` attribute on the stage container (`empty` / `loading` / `done`).

**Empty state:**
- Dashed `--border` box (max 600×600, centered), 2px dash with 8px gap.
- Center: 48×48 image icon in `--text-mute`, then 14px `--text-dim` label "Your image will appear here".

**Loading state:**
- Same dashed box size.
- Contains a skeleton pulse (linear-gradient `surface → surface-2 → surface`, 1.6s infinite animation).
- Centered on the skeleton: 28×28 spinner (CSS-only border rotation) + status text.
- Below the box: a second status line mirroring the one in the control panel, so the user does not need to look at two places.

**Done state:**
- `<img>` element, `max-width: 100%`, `max-height: calc(100vh - 180px)`, `object-fit: contain`, 8px border-radius, `box-shadow: 0 8px 32px #0006`.
- Below the image: **meta bar** — a thin horizontal strip with:
  - Left: prompt truncated to 100 chars with ellipsis.
  - Middle: param summary in monospace, dot-separated: `1024² · 4 steps · seed 12345 · 6.2s`.
  - Right: `Download` (primary ghost) + `Re-run` (ghost). Both 28px height.
- Meta bar styling: 40px min-height, `padding: 8px 16px`, `border: 1px solid --border`, `border-radius: 8px`, `background: --surface`, `margin-top: 16px`.

### 7.4 Control panel (`<section>` or `<aside>`)

Vertical stack, 20px padding, 16px gap between groups.

**Mode segmented control:**
- Two buttons rendered as a single pill: `Text → Image` / `Image → Image`.
- Active segment: `--accent` background, white text.
- Inactive: transparent background, `--text-dim` text, hover `--surface-2`.

**Prompt group:**
- Label "PROMPT" (11px uppercase).
- `<textarea>` — 4 rows, `background: --surface-2`, `border: 1px solid --border`, focus: `border-color: --accent` + `box-shadow: 0 0 0 3px --accent-dim`.

**Dimensions group ("DIMENSIONS"):**
- Two columns for W / H. Monospace inputs. `min 256 · max 1536 · step 64` as a single 11px `--text-mute` hint line below.

**Generation group ("GENERATION"):**
- Two columns for Steps / Seed.
- Steps hint: `schnell sweet spot: 4` in `--text-mute` 11px.
- Seed input: monospace, with a 🎲 button inside the input (right-aligned icon button). Clicking fills a random int in `[0, 2^31 - 1]`.

**Img2img extras group (conditional, visible only when mode = img2img):**
- Drop zone for the init image file — 80px tall dashed box, drag-and-drop + click-to-select, shows thumbnail of loaded file at 56×56 + filename.
- Strength slider: native `<input type="range">` styled in indigo + numeric display to the right.

**Generate button:**
- Full width, 40px tall, `--accent` background, white text, 600 weight.
- Right edge: dim monospace `⌘↵` shortcut hint.
- Disabled state: `--surface-2` background, `--text-mute` text, no hover.

**Status line:**
- 12px, monospace. Three visual forms:
  - Idle: empty / hidden.
  - Running: `● running · 00:03` — indigo pulsing dot + monospace elapsed time, updated every 500ms.
  - Error: `✕ error: <message>` in `--danger`.
  - Done: `✓ done in 6.2s` in `--success` (auto-clears after 3s — optional polish, remove if it causes flicker).

### 7.5 Token modal

- Same `--bg` backdrop at 70% opacity, `backdrop-filter: blur(4px)`.
- Modal card: `--surface`, 1px `--border`, 12px radius, 24px padding, 420px wide.
- Title 16px 600, description 13px `--text-dim`, input matches other inputs, save button matches Generate styling.

## 8. Duration display (new)

Backend already returns `started_at` and `finished_at` as ISO strings in the task detail response (`app/schemas.py:92-93`).

Client computes `duration_ms = Date.parse(finished_at) - Date.parse(started_at)` once per completed task.

Formatting helper:

```js
function formatDuration(ms) {
  if (ms < 1000) return `${(ms / 1000).toFixed(1)}s`;   // e.g., 0.8s
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`; // e.g., 6.2s
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${m}m ${s.toString().padStart(2, "0")}s`;     // e.g., 1m 23s
}
```

Three display sites:

1. **Status line (live while running):** a client-side timer starts when the task status first becomes `running`. Formatted as `mm:ss` using monospace. Stops and is replaced by the final duration on `done`.
2. **Meta bar below the stage image:** appended to the param summary as the last dot-separated token.
3. **History thumbnail chip:** bottom-right overlay as described in §7.2.

### 8.1 History schema change

Add one optional field to stored history entries:

```js
// Before
{ task_id, kind, prompt, params, thumbnail, created_at }

// After
{ task_id, kind, prompt, params, thumbnail, created_at, duration_ms }
```

Old entries without `duration_ms` simply do not render the chip and do not show duration in the restored meta bar. No migration required.

## 9. Interactions and keyboard

- `⌘/Ctrl + Enter` anywhere in the control panel submits the form.
- `Esc` closes the token modal (only when it is open).
- History thumbnail click: restore entry into stage + control panel (existing behavior). Visual selected ring moves to the clicked thumbnail.
- 🎲 button next to Seed: fills a random 32-bit unsigned int.
- Generate button and form submit are the same path.

## 10. State model (client)

One implicit state machine on the stage, driven by generation flow:

```
  empty ──submit──► loading ──done────► done
                      │
                      └──error─► done (shows last successful image if any, otherwise empty)
```

Status line has its own parallel states: `idle`, `submitting`, `queued`, `running`, `done`, `error`.

Timer lifecycle:
- Start timer when first status poll returns `running` (not when submitted, since it may queue).
- Stop timer on `done` or `error`.
- Timer writes to the status line every 500ms.

## 11. File changes

Only one file changes:

- `app/static/index.html` — full rewrite of `<style>`, `<body>`, and `<script>` sections. External behavior (endpoints hit, storage keys, localStorage format aside from the additive `duration_ms` field) stays identical so that `tests/test_routes.py` and any backend tests continue to pass untouched.

## 12. Testing

- No automated UI tests exist in this project; none are added. (The project's existing tests cover backend routes only.)
- Manual verification checklist:
  1. Fresh load without token → modal appears, blurred backdrop visible, save persists token.
  2. `⌘↵` submits the form from inside any input.
  3. Generate with fake pipeline locally: empty → loading with timer ticking → done with duration in meta bar.
  4. History thumbnails show duration chip for new entries and no chip for pre-migration entries.
  5. Clicking a history thumbnail restores its prompt, params, image, and marks it as selected.
  6. Re-run reproduces the same image (same seed).
  7. Clear token re-opens the modal.
  8. Layout holds at 1280px, 1440px, and 1920px widths without horizontal scroll and without squeezing the stage under 500px of image width.

## 13. Risks and open questions

- **Light mode:** removing it is intentional but does mean a user with a bright environment loses an option. Accepted for this rewrite.
- **Mobile:** three-column layout will break under ~900px. Out of scope; the tool is Colab-paired and used on desktop.
- **Status auto-clear:** the 3-second auto-clear of the success status is optional polish; drop it if it causes distraction on back-to-back generations.

## 14. Implementation notes

- Prefer CSS custom properties for all colors and spacings so that future tweaks are one-liners.
- Keep the whole file under ~500 lines to maintain the single-file constraint comfortably.
- Do not introduce icon libraries. Use inline SVG for the few icons needed (image placeholder, dice, download, spinner).
