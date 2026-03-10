# Feature 13 — Web Dashboard

A local web UI at `http://localhost:8741` for chatting, browsing memory, reviewing the audit log, and monitoring DuckClaw's activity.

---

## Intent

A terminal is fine for power users but not for everyone. The dashboard gives DuckClaw a visual interface without compromising the local-first model — it runs entirely on `127.0.0.1`, never on a remote server.

---

## Pages

### Chat (`/`)
Full-featured chat interface connected via WebSocket. Supports:
- Real-time "thinking" indicator while DuckClaw processes
- **Approval popups** for ASK-tier actions — appear as an overlay with Approve/Deny buttons
- Markdown rendering in responses
- Session persistence

### Memory (`/memory`)
Browse stored facts organized by category. Delete individual facts. View memory stats (total facts, conversations, sessions).

### Audit Log (`/audit`)
Searchable table of every action DuckClaw has taken. Filter by:
- Status (approved, denied, blocked, notified)
- Action type
- Tier
- Free-text search

### Settings (`/settings`)
Read-only view of the active configuration — model, memory paths, dashboard port, security settings.

---

## API Endpoints

All API endpoints return JSON.

### Chat
```
POST /api/chat
Body: {"message": "hello", "session_id": "optional"}
Returns: {"reply": "...", "session_id": "..."}
```

Empty messages return `400 Bad Request`.

### Memory
```
GET  /api/memory/facts         → list facts (optional ?category=work)
DELETE /api/memory/facts/{id}  → delete a fact
```

### Audit
```
GET /api/audit                        → list logs
GET /api/audit?q=screenshot           → text search
GET /api/audit?status=blocked         → filter by status
GET /api/audit?tier=ask&limit=50      → filter + paginate
GET /api/audit/export?fmt=json        → download JSON
GET /api/audit/export?fmt=csv         → download CSV
```

### Stats & LLM
```
GET /api/stats        → memory + audit aggregate counts
GET /api/llm/stats    → LLM call history + cost totals
GET /api/skills       → list registered skills
```

### Logs
```
GET /api/logs                              → last 200 log entries
GET /api/logs?level=info                   → filter by level
GET /api/logs?logger_filter=screen_capture → filter by logger name
GET /api/logs?limit=50                     → limit results
```

---

## WebSocket Chat Protocol

The chat page uses a persistent WebSocket at `/ws/chat`.

**Client → Server:**
```json
{"type": "message", "content": "take a screenshot", "session_id": "dashboard-ws"}
{"type": "approval", "action_id": "uuid-here", "approved": true}
```

**Server → Client:**
```json
{"type": "thinking"}
{"type": "response", "content": "...", "session_id": "..."}
{"type": "approval_request", "action_id": "uuid", "preview": {...}}
{"type": "notification", "message": "ℹ️ Browsing example.com"}
{"type": "error", "message": "..."}
```

The approval flow pauses the skill, sends `approval_request` to the browser, then waits up to 120 seconds for the `approval` response before proceeding or timing out.

---

## Starting the Dashboard

```bash
duckclaw start
# or with options:
duckclaw start --port 9000 --no-browser --debug
```

The dashboard auto-opens a browser window 1.5 seconds after startup (configurable with `auto_open_browser: false`).
