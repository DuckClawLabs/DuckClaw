# Feature 3 — Telegram Bridge

Chat with DuckClaw through Telegram. Same capabilities as the web dashboard, delivered to your phone.

---

## Intent

DuckClaw should be reachable wherever you are. The Telegram bridge extends the full assistant — including the Permission Engine — to your mobile. When an action requires approval, you see ✅ Approve and ❌ Deny buttons directly in the chat.

---

## Setup

**1. Create a bot**

Message [@BotFather](https://t.me/BotFather) on Telegram:
```
/newbot
```
Copy the bot token.

**2. Start the bridge**

```bash
duckclaw telegram --token YOUR_BOT_TOKEN
```

Or with an allowlist (only listed user IDs can use the bot):
```bash
duckclaw telegram --token YOUR_BOT_TOKEN --allowed-users 123456,789012
```

Find your Telegram user ID by messaging [@userinfobot](https://t.me/userinfobot).

**3. Set via environment variable**

```bash
export TELEGRAM_BOT_TOKEN=your-token-here
duckclaw telegram
```

---

## Bot Commands

| Command | What it does |
|---------|-------------|
| `/start` | Welcome message and capability overview |
| `/memory` | List stored facts about you |
| `/audit` | Show recent action audit log |
| `/help` | List available commands |

Any other message is treated as a chat message to DuckClaw.

---

## Approval Flow

When DuckClaw needs to perform an ASK-tier action (e.g. take a screenshot, run a shell command), it sends an inline keyboard message:

```
⚠️ Permission Required

Action: Take a screenshot of your screen
Risk: 🟢 LOW | ✓ Reversible
Monitor: 0 | Region: full screen

[ ✅ Approve ]  [ ❌ Deny ]
```

The action is paused until you tap a button or it times out (120 seconds).

---

## Security

- **Allowlist** — When `allowed_users` is set, any message from an unlisted user is silently ignored.
- **Per-chat session isolation** — Each Telegram chat ID gets its own session, isolated from all other conversations.
- **Full Permission Engine** — All 4 tiers apply exactly as in the terminal and dashboard.
