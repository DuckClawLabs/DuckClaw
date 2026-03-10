# Feature 10 — Audit Log

A permanent, searchable record of every action DuckClaw has taken or attempted.

---

## Intent

Trust requires transparency. DuckClaw logs every permission check — approved, denied, notified, and blocked — to a local SQLite database. You can search it, filter it, and export it at any time. There are no hidden actions.

---

## What Is Logged

Every call to `permissions.check()` creates one audit entry, regardless of outcome:

| Field | Description |
|-------|-------------|
| `id` | Auto-incrementing integer |
| `timestamp` | UTC datetime |
| `action_type` | e.g. `screen_capture`, `file_write`, `shell_exec` |
| `tier` | `safe` / `notify` / `ask` / `block` |
| `description` | Plain English description of the action |
| `details` | JSON — specific parameters (path, command, URL, etc.) |
| `status` | `auto_approved` / `notified` / `user_approved` / `user_denied` / `blocked` |
| `source` | `terminal` / `dashboard` / `telegram` / `discord` |
| `session_id` | Which conversation session |
| `reversible` | Whether the action is undoable |
| `risk_level` | `low` / `medium` / `high` |

---

## Dashboard

Browse the audit log at `http://localhost:8741/audit`.

Filter by:
- Action type
- Status (approved, denied, blocked)
- Tier
- Free-text search across description and action_type

---

## API

### Get logs

```
GET /api/audit
GET /api/audit?q=screenshot
GET /api/audit?status=blocked
GET /api/audit?action_type=shell_exec
GET /api/audit?tier=ask&limit=50&offset=0
```

Response:
```json
{
  "logs": [
    {
      "id": 42,
      "timestamp": "2026-03-10 14:23:01",
      "action_type": "screen_capture",
      "tier": "ask",
      "description": "Take a screenshot of your screen",
      "details": {"monitor": 0, "region": "full screen"},
      "status": "user_approved",
      "source": "dashboard",
      "reversible": true,
      "risk_level": "low"
    }
  ],
  "total": 1
}
```

### Export

```
GET /api/audit/export?fmt=json   → downloads duckclaw-audit.json
GET /api/audit/export?fmt=csv    → downloads duckclaw-audit.csv
```

The CSV export includes a header row and all fields. Both formats include the full audit history.

---

## Storage

The audit log is stored in the same SQLite database as facts and conversations:

```
~/.duckclaw/duckclaw.db  →  audit_log table
```

It is indexed on `timestamp`, `action_type`, and `status` for fast filtering. The database is yours — you can query it directly with any SQLite client.
