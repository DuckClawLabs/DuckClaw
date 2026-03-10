# Feature 7 — File Manager

Read, write, list, and delete files — scoped to allowed directories, with a hardcoded credential blocklist.

---

## Intent

File access needs two layers of defense: you control which directories are accessible (allowlist), and certain paths can never be touched regardless of what you configured (credential blocklist). DuckClaw applies both, in that order, for every operation.

---

## Tiers

| Action | Tier | Behavior |
|--------|------|---------|
| `list` | NOTIFY | Directory listing — auto-approved, user informed |
| `read` | NOTIFY | Read file contents — auto-approved, user informed |
| `write` | ASK | Create or overwrite a file — requires approval |
| `delete` | ASK | Delete a file — requires approval (medium risk) |

---

## Credential Blocklist

These path patterns are **always rejected**, regardless of the allowlist. The LLM cannot read or write these paths:

| Pattern | Protects |
|---------|---------|
| `.ssh` | SSH private keys |
| `.gnupg`, `.pgp` | GPG keys |
| `.env` | Environment variable files |
| `credentials` | Credential files |
| `.netrc` | FTP/HTTP credentials |
| `.git/config` | Git credentials (stored in remote URLs) |
| `id_rsa`, `id_ed25519` | SSH key names |
| `*.pem`, `*.key`, `*.p12` | Certificate files |
| `keychain`, `wallet` | Key stores |
| `password`, `secret`, `token`, `api_key` | Sensitive name patterns |

The blocklist check runs **before** the allowlist check. There is no path to a credential file.

---

## Allowlist (Allowed Directories)

By default, DuckClaw only accesses these directories:

```
~/Documents
~/Downloads
~/Desktop
~/Projects
~/duckclaw-workspace
```

Paths outside the allowlist are rejected with "path not in allowed directories."

To add a custom directory, set `allowed_paths` in config or directly on the skill instance.

---

## Actions

### `read`
Read a file's contents. Capped at **1MB**.

```json
{"skill": "file_manager", "action": "read", "params": {"path": "~/Documents/notes.txt"}}
```

### `write`
Write content to a file (creates or overwrites).

```json
{
  "skill": "file_manager",
  "action": "write",
  "params": {
    "path": "~/Documents/output.txt",
    "content": "Hello from DuckClaw"
  }
}
```

### `list`
List files and directories at a path.

```json
{"skill": "file_manager", "action": "list", "params": {"path": "~/Documents"}}
```

Returns a formatted string of file names with sizes and modification times.

### `delete`
Delete a file. **ASK tier, medium risk, irreversible.**

```json
{"skill": "file_manager", "action": "delete", "params": {"path": "~/Documents/old-file.txt"}}
```

The approval preview explicitly marks this as irreversible.

---

## Limits

- Max file read: **1MB** — larger files are rejected with a size error
- Paths are resolved to absolute paths before all checks (prevents `../` traversal)
