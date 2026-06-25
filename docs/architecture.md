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
| Background jobs | TBD |
| Deployment | TBD |

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

## System Diagram

```
User (Next.js)
  │
  ├── API calls ──────────→ Backend API
  │                           ├── Supabase (DB + pgvector)
  │                           ├── Gemini API (AI calls)
  │                           ├── GitHub API (read only)
  │                           └── Background jobs (reconciliation polling)
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
    │   ├── ingest.py
    │   ├── projects.py
    │   ├── webhooks.py
    │   └── dashboard.py
    ├── services/
    │   ├── ai.py
    │   ├── matching.py
    │   └── github.py
    └── models/
```
