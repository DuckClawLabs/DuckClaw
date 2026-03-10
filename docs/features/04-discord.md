# Feature 4 — Discord Bridge

Chat with DuckClaw through Discord. Supports slash commands and button-based approval flows.

---

## Intent

Discord is where many developer communities live. DuckClaw's Discord bridge brings the full assistant — including the Permission Engine approval system — into Discord channels and DMs, with native button UI for approvals.

---

## Setup

**1. Create a bot**

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application → Bot → Reset Token
3. Enable **Message Content Intent** under Privileged Gateway Intents
4. Invite the bot to your server with `bot` + `applications.commands` scopes

**2. Start the bridge**

```bash
duckclaw discord --token YOUR_BOT_TOKEN
```

For faster slash command registration on a specific server:
```bash
duckclaw discord --token YOUR_BOT_TOKEN --guild-ids 123456789
```

**3. Set via environment variable**

```bash
export DISCORD_BOT_TOKEN=your-token-here
duckclaw discord
```

---

## Slash Commands

| Command | What it does |
|---------|-------------|
| `/chat <message>` | Send a message to DuckClaw |
| `/memory` | List stored facts |
| `/audit` | Show recent audit log entries |
| `/help` | Show available commands |

---

## Approval Flow

When an ASK-tier action is needed, DuckClaw sends an embed with buttons:

```
┌────────────────────────────────────────┐
│  ⚠️ Permission Required                │
│                                        │
│  Action: Write file output.txt         │
│  Risk: 🟢 LOW | ✓ Reversible          │
│  Path: ~/Documents/output.txt          │
│                                        │
│  [ ✅ Approve ]    [ ❌ Deny ]         │
└────────────────────────────────────────┘
```

The `ApprovalView` component handles button interactions. The action waits up to 120 seconds.

---

## Security

- **Per-channel session isolation** — Each Discord channel gets its own session.
- **Guild scoping** — Slash commands can be restricted to specific guild IDs.
- **Full Permission Engine** — All 4 tiers apply.

---

## Dependencies

```bash
pip install "discord.py>=2.3"
```
