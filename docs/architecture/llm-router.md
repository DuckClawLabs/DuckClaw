# LLM Router

The LLM Router is DuckClaw's unified interface to language models. It handles model selection, automatic failover, and cost tracking.

---

## How It Works

```
chat(messages, system_prompt)
         │
         ▼
   Primary model
   (e.g. Claude Haiku)
         │
    ┌────┴────┐
  Success   Failure
    │          │
    ▼          ▼
  Return    Try fallback #1
            (Gemini Flash)
                │
           ┌────┴────┐
         Success   Failure
            │          │
            ▼          ▼
          Return    Try fallback #2
                    ... and so on
```

Every call — success or failure — is logged with token counts, cost, and latency.

---

## Supported Models

Any model string supported by [LiteLLM](https://docs.litellm.ai/docs/providers):

| Model | String | Notes |
|-------|--------|-------|
| Claude Sonnet | `claude-sonnet-4-6` | Most capable |
| Claude Haiku | `claude-haiku-4-5-20251001` | Fast, low cost |
| Gemini Flash | `gemini/gemini-2.0-flash` | Free tier, good fallback |
| GPT-4o | `openai/gpt-4o` | Requires OpenAI key |

---

## Cost Tracking

Every call records:
- `prompt_tokens` / `completion_tokens` / `total_tokens`
- `cost_usd` — estimated cost from LiteLLM pricing tables
- `latency_ms` — wall-clock time
- `model` — which model actually responded (may be a fallback)

Aggregate stats are available at `GET /api/llm/stats`:

```json
{
  "stats": {
    "total_calls": 42,
    "total_cost_usd": 0.0031,
    "total_tokens": 18500,
    "successful_calls": 41,
    "failed_calls": 1,
    "fallback_used": 3
  }
}
```

---

## Dual Prompts

The router receives one of two system prompts depending on the message:

- **Conversational** — for greetings, questions, writing, coding. No JSON skill grammar. The LLM cannot emit a tool call because the grammar is not in the prompt.
- **Skills-enabled** — for messages that contain keywords like "search", "run", "screenshot". Full skill call JSON format included.

This prevents the common failure mode where a casual message like "run me through the Python docs" accidentally triggers a shell command.
