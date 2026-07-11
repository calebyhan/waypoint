# Architecture

## Tech Stack

### Frontend

| Layer | Choice |
|---|---|
| Framework | Next.js 15 (App Router) |
| Styling | Tailwind CSS |
| Components | shadcn/ui |
| Client state | Zustand |
| Server state | TanStack Query |
| Deployment | TBD |

### Backend

| Layer | Choice |
|---|---|
| Framework | FastAPI (Python) |
| Validation | Pydantic |
| Background jobs | APScheduler (in-process `AsyncIOScheduler`, started in `main.py`'s lifespan) |
| Deployment | TBD |

Scheduled jobs (`backend/core/scheduler.py`):

- Reconciliation poll -- every 15 min
- Insight generation -- every 24 h
- GitHub write-back outbox drain -- every 2 min

### Data

| Layer | Choice |
|---|---|
| Database | Supabase (PostgreSQL) |
| Vector storage | pgvector extension on Supabase |
| Real-time | Supabase real-time subscriptions |

### Integrations

| Service | Purpose |
|---|---|
| Gemini 3.1 Flash Lite | LLM calls (500 RPD per key) |
| Gemini Embedding 2 | Task embeddings (1K RPD per key) |
| GitHub OAuth | Auth + repo access |
| GitHub Webhooks | Issue/PR event listening |
| GitHub REST API | Issue read + write-back (create/edit/close/reopen issues linked to tasks) |

## System Diagram

```
User (Next.js)
  │
  ├── API calls ──────────→ Backend API
  │                           ├── Supabase (DB + pgvector)
  │                           ├── Gemini API (AI calls)
  │                           ├── GitHub API (read + issue write-back)
  │                           └── Background jobs (reconciliation, insights,
  │                                 write-back outbox drain)
  │
  ├── Real-time updates ←── Supabase real-time subscriptions
  │
  └── GitHub Webhooks ────→ Backend API
                              └── Match issue → update task → Supabase
                                    └── Supabase real-time → dashboard
```

## Folder Structure

```
waypoint/
├── frontend/               # Next.js
│   ├── app/
│   ├── components/
│   └── lib/
└── backend/                # FastAPI
    ├── main.py
    ├── routers/
    │   ├── auth.py
    │   ├── dashboard.py
    │   ├── ingest.py
    │   ├── projects.py
    │   ├── webhooks.py
    │   └── workspaces.py
    ├── services/
    │   ├── ai.py
    │   ├── diff.py
    │   ├── github.py
    │   ├── github_sync.py
    │   ├── github_writeback.py
    │   ├── insights.py
    │   ├── matching.py
    │   ├── pdf.py
    │   ├── reconcile.py
    │   └── scheduling.py
    ├── models/
    │   └── decomposition.py
    └── core/
```
