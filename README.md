# Waypoint

AI-powered project management for small engineering teams (2-10 people). Drop in a PRD, get a scoped task breakdown, track progress via GitHub.

## What It Does

1. PM pastes a PRD or rough notes
2. AI proposes epics and PR-sized tasks
3. PM edits and approves the plan
4. Waypoint tracks progress by listening to GitHub issues and PRs (read-only)

## Core Principles

- **Propose, don't act** -- the agent proposes, the PM approves
- **GitHub is the source of truth** -- Waypoint reads and listens, never writes
- **Free to use** -- built on free-tier infrastructure

## Tech Stack

- **Frontend:** Next.js 15, Tailwind CSS, shadcn/ui, Zustand, TanStack Query
- **Backend:** FastAPI, Pydantic
- **Data:** Supabase (PostgreSQL + pgvector + real-time)
- **AI:** Gemini 3.1 Flash Lite, Gemini Embedding 2

## Project Structure

```
waypoint/
├── frontend/               # Next.js
│   ├── app/
│   ├── components/
│   └── lib/
├── backend/                # FastAPI
│   ├── main.py
│   ├── routers/
│   ├── services/
│   └── models/
└── docs/                   # Project documentation
```

## Documentation

- [Product](docs/product.md) -- problem, users, principles, screens
- [Data Model](docs/data-model.md) -- tasks, epics, statuses, dependencies
- [GitHub Integration](docs/github-integration.md) -- webhooks, matching, reconciliation
- [AI Stack](docs/ai-stack.md) -- models, rate limits, caching, failure handling
- [Architecture](docs/architecture.md) -- tech stack, integrations, folder structure
- [Agent Behaviors](docs/agent-behaviors.md) -- triggers, actions, re-ingestion
- [Build Order](docs/build-order.md) -- phased build sequence, v1 scope

## Setup

1. Create a [Supabase](https://supabase.com/dashboard) project, then link and push the schema:
   ```
   supabase login
   supabase link --project-ref <your-project-ref>
   supabase db push
   ```
2. Register a [GitHub OAuth App](https://github.com/settings/developers) with callback URL `https://<your-project-ref>.supabase.co/auth/v1/callback`, then enable it on the Supabase project:
   ```
   SUPABASE_AUTH_EXTERNAL_GITHUB_CLIENT_ID=... SUPABASE_AUTH_EXTERNAL_GITHUB_SECRET=... supabase config push
   ```
3. Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env.local`, filling in your Supabase URL/keys and GitHub OAuth credentials.
4. Run both apps:
   ```
   cd backend && pip install -e ".[dev]" && uvicorn main:app --reload
   cd frontend && npm install && npm run dev
   ```
5. Open `http://localhost:3000/login` and sign in with GitHub.

Each PM also needs a free [Gemini API key](https://aistudio.google.com/apikey), added from the onboarding screen after first login.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
