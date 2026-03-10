# Feature 1 — Screen Capture

Capture screenshots of your desktop and optionally analyze them with AI vision.

**Tier: ASK — explicit approval required for every capture.**

---

## Intent

You should always know when something is looking at your screen. DuckClaw cannot take a screenshot silently. Every capture pauses and waits for your yes or no before anything happens.

---

## Actions

### `capture`
Take a screenshot of a monitor. Returns the image as base64 JPEG.

```json
{"skill": "screen_capture", "action": "capture", "params": {"monitor": 0}}
```

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `monitor` | int | `0` | Monitor index (0 = primary, or all monitors) |
| `region` | dict | full screen | `{"top": y, "left": x, "width": w, "height": h}` |

### `capture_analyze`
Capture a screenshot and immediately send it to the LLM vision model with a question.

```json
{
  "skill": "screen_capture",
  "action": "capture_analyze",
  "params": {
    "monitor": 0,
    "question": "What application is open and what does it show?"
  }
}
```

Returns the LLM's analysis of the screen.

### `list_monitors`
List available monitors and their resolutions. Tier: **SAFE** (no image captured).

```json
{"skill": "screen_capture", "action": "list_monitors", "params": {}}
```

---

## Security

- Every `capture` and `capture_analyze` call is **ASK-tier** — no silent captures ever.
- Images are **not saved to disk** by default. Returned as base64 in memory.
- Images are compressed to JPEG (≤5MB) before sending to the LLM.
- If the image is too large (>4MB), it is resized to 1920×1080 at quality 75.
- The approval callback carries the monitor number and region so you know exactly what will be captured.

---

## Dependencies

```bash
pip install mss Pillow
```

`mss` is cross-platform (macOS, Windows, Linux) with no system-level dependencies.

---

## Logging

All events are logged under `duckclaw.skills.screen_capture`:

| Event | Level | Message |
|-------|-------|---------|
| Action dispatched | INFO | `execute action=capture params={...}` |
| Approval requested | INFO | `requesting ASK-tier approval — monitor=0 region=full screen` |
| Approved / Denied | INFO | `capture APPROVED` / `capture DENIED by user` |
| Capture success | INFO | `capture SUCCESS — 1920×1080 px, 312KB` |
| Image too large | INFO | `image too large (5100KB) — resizing` |
| Vision response | INFO | `LLM vision response received (427 chars)` |
| Error | ERROR | `capture failed: <reason>` |

View logs in the dashboard at `GET /api/logs?logger_filter=screen_capture`.
