# Permission Engine

The Permission Engine is DuckClaw's core safety system. Every action — file read, shell command, screenshot, web form submission — passes through it before execution.

**Intent:** Make it structurally impossible for DuckClaw to take a harmful action without your knowledge. Not policy. Code.

---

## The Four Tiers

```
SAFE    ──► Auto-approved, no notification
NOTIFY  ──► Auto-approved, user informed
ASK     ──► Paused until user explicitly approves
BLOCK   ──► Rejected immediately, cannot be unlocked
```

### SAFE
Actions with no side effects. Reading memory, answering questions from knowledge, listing monitors. Executed silently.

### NOTIFY
Read-only access to external systems. Browsing the web, reading a file, running `ls`. Executed automatically but logged and surfaced in the dashboard.

### ASK
Real-world side effects. Taking a screenshot, writing a file, running an unknown shell command, sending a message. DuckClaw pauses and presents an **Action Preview** to the user. Nothing happens until you approve.

### BLOCK
Hardcoded permanently. These can never be unlocked by config, chat, or any instruction:

| Action type | What it prevents |
|-------------|-----------------|
| `access_credentials` | Reading SSH keys, `.env` files, API keys |
| `sudo_command` | Any `sudo` usage |
| `rm_recursive_root` | `rm -rf /` or `rm -rf ~` |
| `curl_pipe_bash` | `curl ... | bash` or `wget ... | sh` |
| `format_disk` | `mkfs.*` commands |
| `write_raw_disk` | Writing to `/dev/sd*` |
| `fork_bomb` | `: () { : | : & }` |

These are enforced in Python code, not configuration. An LLM cannot talk its way past them.

---

## Action Preview

Before any ASK-tier action executes, the user sees:

```
==================================================
⚠️  Permission Required
Action: Take a screenshot of your screen
Risk: 🟢 LOW  |  ✓ Reversible
Details:
  monitor: 0
  region: full screen
==================================================
```

The preview includes:
- `action_type` — what category of action
- `description` — plain English explanation
- `risk_level` — low / medium / high
- `reversible` — whether the action can be undone
- `details` — specific parameters (file path, command, URL, etc.)

---

## Default Action Classification

| Action type | Tier | Example |
|------------|------|---------|
| `chat_response` | SAFE | Answering a question |
| `memory_read` | SAFE | Loading conversation history |
| `memory_search` | SAFE | Semantic memory search |
| `web_search` | SAFE | DuckDuckGo query |
| `list_files` | SAFE | Listing directory contents |
| `file_read` | NOTIFY | Reading an allowed file |
| `web_browse` | NOTIFY | Navigating to a URL |
| `shell_safe` | NOTIFY | Running `ls`, `git status`, `df` |
| `browser_screenshot` | NOTIFY | Screenshot of a web page |
| `screen_capture` | ASK | Screenshot of your desktop |
| `camera_capture` | ASK | Webcam photo |
| `file_write` | ASK | Writing or creating a file |
| `file_delete` | ASK | Deleting a file |
| `shell_exec` | ASK | Running an unrecognised command |
| `send_email` | ASK | Sending a message externally |
| `browser_navigate` | ASK | Navigating to a URL via browser |

Unknown action types default to **ASK**.

---

## Approval Callbacks

The Permission Engine is interface-agnostic. Each interface registers its own way of asking the user:

```python
# Terminal: built-in fallback
engine._terminal_prompt(preview)  # prints to stdout, reads input()

# Web dashboard: WebSocket message
await websocket.send_json({"type": "approval_request", "preview": preview.to_dict()})
# waits up to 120 seconds for {"type": "approval", "approved": true}

# Telegram: inline keyboard buttons (✅ / ❌)
# Discord: ApprovalView button components
```

---

## Audit Trail

Every `check()` call — regardless of outcome — is logged to the SQLite `audit_log` table:

```sql
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY,
    timestamp   TEXT,
    action_type TEXT,
    tier        TEXT,
    description TEXT,
    details     TEXT,        -- JSON
    status      TEXT,        -- auto_approved | notified | user_approved | user_denied | blocked
    source      TEXT,        -- terminal | dashboard | telegram | discord
    session_id  TEXT,
    reversible  INTEGER,
    risk_level  TEXT
);
```

Browse it at `GET /api/audit` or export at `GET /api/audit/export?fmt=json`.
