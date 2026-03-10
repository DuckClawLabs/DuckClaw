# Feature 5 — Persistent Memory

DuckClaw remembers facts about you across conversations and can search past conversations semantically.

---

## Intent

A personal assistant that forgets everything every session is barely an assistant. DuckClaw remembers structured facts about you (preferences, work context, recurring details) and stores full conversation history for semantic retrieval. All of it stays on your machine.

---

## Two Storage Layers

```
Facts (SQLite)              Conversations (SQLite + ChromaDB)
──────────────              ──────────────────────────────────
User works at Acme Corp     Full message history per session
User prefers dark mode      Embedded as vectors in ChromaDB
User is a Python dev        Semantic search: "when did I ask about X?"
```

### Facts
Structured key facts extracted automatically from conversations (or added manually). Categorized and searchable. Survive process restart.

### Conversations
Full message history per session, stored in SQLite. Also embedded in ChromaDB for semantic similarity search — so you can ask "what did we discuss about deployment?" and get relevant past context.

---

## API Reference

### Facts

```python
# Save a fact
fact_id = store.save_fact("User works at Acme Corp", category="work")

# List all facts
facts = store.list_facts()
# [{"id": 1, "fact": "...", "category": "work", "created_at": "..."}, ...]

# Filter by category
work_facts = store.list_facts(category="work")

# Delete a fact
store.delete_fact(fact_id)  # returns True/False

# Summarize facts as a formatted string (used in prompts)
summary = store.get_facts_summary()
```

### Conversation History

```python
# Save a message
msg_id = store.save_message(session_id, role, content, source)
# role: "user" | "assistant"
# source: "terminal" | "dashboard" | "telegram" | "discord"

# Get session history
history = store.get_session_history(session_id, limit=20)
# [{"role": "user", "content": "...", "created_at": "..."}, ...]
```

### Semantic Search

```python
# Search across all conversation history
results = store.search_memory("Python developer startup", n_results=5)
# ["I work as a Python developer at a startup", ...]
```

Returns plain text strings of the most semantically similar messages. Falls back to SQLite LIKE search if ChromaDB is unavailable.

### Stats

```python
stats = store.get_stats()
# {
#   "total_facts": 42,
#   "total_messages": 387,
#   "total_sessions": 12,
#   "semantic_index_size": 387
# }
```

---

## Automatic Fact Extraction

After every conversation turn, DuckClaw asynchronously extracts facts from the exchange using a small LLM call. These are saved to the facts table and surfaced in future sessions.

This runs in the background — it does not delay the response to the user.

---

## Dashboard

Browse and manage memory at `http://localhost:8741/memory`:
- View all facts by category
- Delete individual facts
- See storage stats

API endpoints:
- `GET /api/memory/facts` — list facts (optional `?category=work`)
- `DELETE /api/memory/facts/{id}` — delete a fact
- `GET /api/stats` — memory + audit stats
