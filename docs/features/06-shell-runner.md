# Feature 6 — Shell Runner

Execute shell commands with a three-tier safety classification system.

---

## Intent

Shell access is the most powerful — and most dangerous — thing an AI assistant can have. DuckClaw's shell runner makes a clear distinction between safe read-only commands (auto-approved, you're informed), unknown commands (paused until you approve), and destructive patterns (rejected immediately, no override possible).

The blocklist is code, not config. An LLM cannot talk its way around it.

---

## Tiers

| Tier | Actions | Examples |
|------|---------|---------|
| **NOTIFY** | Safe read-only commands | `ls`, `cat`, `git status`, `df`, `ps`, `pip list` |
| **ASK** | Unknown commands | `touch file.txt`, `python script.py`, custom programs |
| **BLOCK** | Hardcoded dangerous patterns | `rm -rf /`, `sudo`, `curl | bash`, `mkfs`, `dd if=` |

---

## Hardcoded Block Patterns

These patterns are matched by regex before any subprocess is created. They cannot be approved, overridden, or bypassed:

| Pattern | What it prevents |
|---------|-----------------|
| `rm -rf /` or `rm -rf ~` | Recursive delete from root or home |
| `rm --no-preserve-root` | Deliberate root deletion |
| `sudo ...` | Privilege escalation |
| `su -` | Switch user |
| `curl ... | bash` | Remote code execution |
| `wget ... | sh` | Remote code execution |
| `: () { : | : & }` | Fork bomb |
| `dd if=` | Raw disk read/write |
| `mkfs.*` | Filesystem format |
| `> /dev/sd*` | Raw disk write |
| `chmod 777 /` | World-write on root |
| `chown -R ... /` | Recursive chown on root |
| `iptables -F` | Flush firewall rules |
| `systemctl disable` | Disable system services |

---

## Safe Command List

These prefixes are classified as NOTIFY (auto-approved, user informed):

```
ls, ll, la, l
cat, head, tail, wc, nl
echo, printf
grep, awk, sed
find, locate
pwd, whoami, id, uptime, date, cal
df, du, free, top -bn1
ps, pgrep
git status, git log, git diff, git branch, git stash list
python --version, python3 --version
pip list, pip show, pip freeze
node --version, npm list
which, type, man
sort, uniq, cut, tr
env, printenv
uname, lsb_release
curl -s, curl --silent  (read-only, no pipe)
ping -c
```

---

## Actions

### `run`
Execute a shell command.

```json
{"skill": "shell_runner", "action": "run", "params": {"command": "git log --oneline -10"}}
```

Returns stdout + stderr. Output is capped at **8,000 characters** with a truncation notice.

### `check_safe`
Classify a command without running it.

```json
{"skill": "shell_runner", "action": "check_safe", "params": {"command": "rm -rf /"}}
```

Returns:
```json
{
  "safe": false,
  "tier": "block",
  "reason": "Recursive delete from root/home"
}
```

---

## Timeouts and Output

- Default timeout: **30 seconds**
- Maximum output: **8,000 characters** (with `[output truncated]` notice)
- Both stdout and stderr are captured and returned together
