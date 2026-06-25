# AI Stack

## Models

| Use Case | Model | Notes |
|---|---|---|
| PRD decomposition | Gemini 3.1 Flash Lite | Structured JSON output via Pydantic schema; 500 RPD headroom |
| Clarifying questions | Gemini 3.1 Flash Lite | Lightweight, up to 3 questions |
| Semantic issue matching | Gemini Embedding 2 + pgvector | Cosine similarity; 1K RPD |
| Insight generation | Gemini 3.1 Flash Lite | Runs on schedule or on-demand |
| Scope gap detection | Gemini 3.1 Flash Lite | Triggered by webhook events |

## Free Tier Rate Limits (per API key)

| Model | RPM | TPM | RPD |
|---|---|---|---|
| Gemini 3.1 Flash Lite | 15 | 250K | 500 |
| Gemini Embedding 2 | 100 | 30K | 1,000 |

RPD (requests per day) is the binding constraint. Most other models on the Gemini free tier have only 20 RPD, making them unusable for production workloads.

## Per-Account API Keys

Each PM provides their own Gemini API key during onboarding. If AI features extend to team members in the future, they provide keys too.

This gives Waypoint:

- **Linear scaling** -- each account adds 500 RPD for text and 1K RPD for embeddings
- **Per-user usage tracking** -- the dashboard shows each account's AI usage (requests today, tokens this month)
- **Rate limit isolation** -- one PM's heavy usage doesn't starve another
- **Key rotation** -- if a key is rate-limited or revoked, only that account is affected; others continue working

AI calls are routed through the key of the PM who owns the workspace. For shared workspaces, the workspace creator's key is used by default; the PM can reassign this in workspace settings.

## Caching Strategy

To minimize API calls:

- **Embedding cache** -- task embeddings are stored in pgvector and only recomputed when a task's title or description changes
- **Decomposition cache** -- identical PRD content returns the cached result instead of re-calling the API
- **Match result cache** -- once a PM confirms or rejects a proposed link, the same issue/task pair is never re-proposed

## Failure Handling

When the agent produces low-quality or failed output:

| Failure | UX |
|---|---|
| API timeout or error | Show error state with a **Retry** button |
| Bad decomposition (too vague, missing tasks) | PM can click **Regenerate** with optional guidance ("focus more on backend tasks") |
| Clarifying questions don't make sense | PM can skip questions and proceed directly to manual task creation |
| Matching proposes a wrong link | PM clicks **No** on the toast; agent learns from rejection for future matches in that workspace |

The PM can always fall back to manually creating epics and tasks from scratch -- the agent is a starting point, not a gate.

## Decomposition Output Schema

```json
{
  "epics": [
    {
      "title": "Authentication",
      "tasks": [
        {
          "title": "Implement JWT login endpoint",
          "description": "...",
          "estimated_days": 2,
          "priority": "p0",
          "dependencies": []
        }
      ]
    }
  ]
}
```

## Budget Estimates (per workspace/month)

### Requests

| Action | Requests/day (typical) |
|---|---|
| PRD decomposition | 0-2 |
| Clarifying questions | 0-1 |
| Issue/PR matching | 1-10 (depends on dev activity) |
| Daily insight run | 1 |
| Scope gap checks | 1-3 |
| **Typical daily total** | **~5-15 requests** |

At 500 RPD per key, a single PM's key supports ~30 active workspaces before hitting limits. With per-account keys, this scales linearly.

### Tokens

| Action | Tokens | Notes |
|---|---|---|
| Decompose a PRD | ~6,000 | Per ingestion; re-ingestion costs the same |
| Clarifying questions | ~500 | Per ingestion |
| Daily insight run | ~2,000 | Scales with number of active tasks |
| Matching (embeddings) | negligible | Stored in pgvector after first computation |
| Re-ingestion diff | ~8,000 | Requires full plan context + new PRD |
| **Typical month** | **~30-50k** | Assumes 2-3 re-ingestions, daily insights |

Well within the 250K TPM limit.
