# Feature 11 — Camera

Capture photos from a webcam or connected camera with AI vision analysis.

**Tier: ASK — explicit approval required for every capture.**

---

## Intent

A camera is an intimate sensor. DuckClaw cannot take a photo without your explicit approval, every single time. Images are not saved to disk by default — they are returned as base64 in memory and discarded after the session.

---

## Actions

### `snap`
Capture a single frame from a camera.

```json
{"skill": "camera", "action": "snap", "params": {"camera_index": 0}}
```

| Param | Default | Description |
|-------|---------|-------------|
| `camera_index` | `0` | Camera index (0 = first/primary camera) |
| `save_path` | none | If provided, save the image to this path (ASK-tier for the file write too) |

Returns base64-encoded JPEG.

### `snap_analyze`
Capture a photo and immediately analyze it with LLM vision.

```json
{
  "skill": "camera",
  "action": "snap_analyze",
  "params": {
    "camera_index": 0,
    "question": "What do you see in this photo?"
  }
}
```

### `list_cameras`
Detect available camera indices. **Tier: SAFE** (no image captured).

```json
{"skill": "camera", "action": "list_cameras", "params": {}}
```

Returns a list of detected camera indices (e.g. `[0, 1]`).

---

## Security

- **ASK tier for all captures** — no silent photos ever
- **Not saved to disk** unless you explicitly provide a `save_path` (which itself requires ASK approval for the file write)
- **Camera closed immediately** after each snap — no persistent stream or background capture
- **No automatic uploads** — images stay local unless you explicitly ask DuckClaw to send them somewhere

---

## Dependencies

Camera support is an optional extra to keep the base install lightweight:

```bash
pip install "duckclaw[camera]"
# equivalent to:
pip install opencv-python
```

If OpenCV is not installed, camera actions return a clear error message with the install command.
