# Model Configuration — Production (Paid Tier)

These are the paid-tier models used before switching to free alternatives.
Restore these when credits are available.

| Role | Model ID | Notes |
|------|----------|-------|
| LLM (audit/chat/revise/draft) | `anthropic/claude-sonnet-4-5` | Best reasoning quality |
| Classifier (domain routing) | `google/gemini-2.5-flash` | Fast, cheap intake |
| Embedding | `qwen/qwen3-embedding-8b` | Used to build all corpus indexes — changing breaks retrieval |

## .env values

```env
LLM_MODEL=anthropic/claude-sonnet-4-5
CLASSIFIER_MODEL=google/gemini-2.5-flash
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
```
