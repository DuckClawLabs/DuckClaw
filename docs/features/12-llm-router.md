# Feature 12 — LLM Router

A unified interface to 100+ language models with automatic failover, cost tracking, and smart prompt routing.

---

## Intent

You should not have to think about which model is running or whether it is available. The router handles primary model selection, falls back transparently when the primary fails, tracks every token spent, and picks the right prompt style for each message.

---

## Model Selection

Configure in `~/.duckclaw/duckclaw.yaml`:

```yaml
llm:
  model: "claude-haiku-4-5-20251001"
  fallback_models:
    - "gemini/gemini-2.0-flash"
```

The router tries the primary model first. If it fails (rate limit, API error, timeout), it tries each fallback in order. All of this is transparent to the user.

---

## Dual System Prompts

The router receives one of two prompts from the Orchestrator:

### Conversational Prompt
Used when the message is conversational — greetings, questions, writing, coding help. Contains **no skill call grammar**. The model cannot emit a JSON skill call because the format is not in the prompt.

**When selected:** message does not contain skill-trigger keywords.

```
"hi" → conversational
"what is Python's GIL?" → conversational
"write me a cover letter" → conversational
```

### Skills-Enabled Prompt
Used when the message requires a real-world action. Contains the full JSON skill call format and the available skill table.

**When selected:** message contains keywords like `search`, `run`, `screenshot`, `remind me`, `read file`, `open website`, etc.

```
"search for Python 3.13 release notes" → skills
"take a screenshot of my screen" → skills
"run git log" → skills
"remind me in 30 minutes to check the build" → skills
```

---

## Cost Tracking

Every call is logged with:

| Field | Example |
|-------|---------|
| Model | `claude-haiku-4-5-20251001` |
| Prompt tokens | `342` |
| Completion tokens | `87` |
| Total tokens | `429` |
| Cost (USD) | `$0.000043` |
| Latency (ms) | `612` |
| Success | `true` |

Aggregate view at `GET /api/llm/stats`:

```json
{
  "stats": {
    "total_calls": 84,
    "total_cost_usd": 0.0062,
    "total_tokens": 37200,
    "successful_calls": 82,
    "failed_calls": 2,
    "fallback_used": 5,
    "avg_cost_per_call": 0.0000757
  }
}
```

Recent calls at `GET /api/llm/stats` → `recent_calls` array.

---

## Supported Providers

DuckClaw uses [LiteLLM](https://docs.litellm.ai) for model calls, supporting all providers LiteLLM supports:

| Provider | Example model string |
|----------|---------------------|
| Anthropic | `claude-sonnet-4-6` |
| Google | `gemini/gemini-2.0-flash` |
| OpenAI | `openai/gpt-4o` |
| Azure | `azure/gpt-4o` |
| Ollama (local) | `ollama/llama3` |
| Any LiteLLM-compatible | see LiteLLM docs |
