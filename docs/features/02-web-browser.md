# Feature 2 — Web Browser

Playwright-powered web automation. Navigate pages, click elements, fill forms, and extract structured content.

---

## Intent

Web browsing is powerful but risky. DuckClaw separates read-only navigation (NOTIFY — automatic) from state-changing actions like form submission (ASK — requires approval). You are always informed when DuckClaw visits a URL, and you must approve before it submits anything.

---

## Actions

### `search`
Search DuckDuckGo and return a list of results. **Tier: SAFE** (no browser opened).

```json
{"skill": "web_browser", "action": "search", "params": {"query": "Python asyncio tutorial"}}
```

Returns a list of `{title, href, body}` dicts.

### `navigate`
Load a URL and return the page title and text content. **Tier: ASK** (browser opens, network call made).

```json
{"skill": "web_browser", "action": "navigate", "params": {"url": "https://example.com"}}
```

Returns `{"title": "...", "content": "...", "url": "..."}`. Content is capped at 50,000 characters.

### `click`
Click an element by CSS selector or visible text. **Tier: ASK**.

```json
{
  "skill": "web_browser",
  "action": "click",
  "params": {"selector": "button.submit", "text": "Sign in"}
}
```

### `fill_form`
Fill one or more form fields. **Tier: ASK**. Submission requires separate approval.

```json
{
  "skill": "web_browser",
  "action": "fill_form",
  "params": {
    "fields": {"#username": "alice", "#email": "alice@example.com"},
    "submit": false
  }
}
```

### `extract_text`
Extract structured text and links from the current page. **Tier: NOTIFY**.

```json
{"skill": "web_browser", "action": "extract_text", "params": {}}
```

### `screenshot`
Take a screenshot of the current browser page (not your desktop). **Tier: NOTIFY**.

```json
{"skill": "web_browser", "action": "screenshot", "params": {}}
```

---

## Security

### URL Blocklist
These URL patterns are **rejected before any network call**:

| Pattern | Reason |
|---------|--------|
| `localhost`, `127.0.0.1` | Prevent access to local services |
| `192.168.*`, `10.*`, `172.16-31.*` | Private network ranges |
| `file://` | Local filesystem access |
| `*.onion` | Tor hidden services |

### Session Isolation
Each browser session uses an isolated context — no shared cookies, storage, or credentials between sessions.

### Timeouts
All actions time out after **30 seconds**. A stuck page does not block DuckClaw.

---

## Dependencies

```bash
pip install playwright
playwright install chromium
```
