# Feature 8 — Scheduler

Schedule reminders, cron jobs, and recurring background tasks using APScheduler.

**Tier: ASK — creating a schedule requires approval.**

---

## Intent

Proactive tasks are useful but should not happen without your knowledge. DuckClaw requires approval before scheduling any job, and delivers notifications through whatever interface you are currently using (terminal, dashboard, Telegram, Discord).

---

## Actions

### `remind_in`
Schedule a one-time reminder after a delay.

```json
{
  "skill": "scheduler",
  "action": "remind_in",
  "params": {
    "minutes": 30,
    "message": "Check the deployment logs"
  }
}
```

| Param | Type | Description |
|-------|------|-------------|
| `minutes` | int | Minutes from now (must be > 0 if `hours` is 0) |
| `hours` | int | Hours from now |
| `message` | str | Reminder text |

Returns a `job_id` in metadata.

### `remind_at`
Schedule a one-time reminder at a specific time.

```json
{
  "skill": "scheduler",
  "action": "remind_at",
  "params": {
    "time": "14:30",
    "message": "Stand-up meeting"
  }
}
```

### `add_cron`
Schedule a recurring job with a cron expression.

```json
{
  "skill": "scheduler",
  "action": "add_cron",
  "params": {
    "cron": "0 9 * * 1-5",
    "message": "Morning briefing"
  }
}
```

### `list_jobs`
List all scheduled jobs. **Tier: SAFE**.

```json
{"skill": "scheduler", "action": "list_jobs", "params": {}}
```

### `remove_job`
Cancel a scheduled job.

```json
{"skill": "scheduler", "action": "remove_job", "params": {"job_id": "abc-123"}}
```

---

## Notification Delivery

When a scheduled job fires, the notification is delivered through the active interface:

| Interface | Delivery |
|-----------|---------|
| Terminal | Printed to stdout |
| Web Dashboard | WebSocket message to browser |
| Telegram | Telegram message to your chat |
| Discord | Discord message to the channel |

---

## Validation

- `minutes=0` with `hours=0` is rejected — a reminder must be in the future
- Invalid cron expressions are caught before any job is created
- Job IDs are UUIDs generated at creation time

---

## Dependencies

```bash
pip install apscheduler
```

If APScheduler is not installed, the scheduler skill is disabled and returns a clear error message.
