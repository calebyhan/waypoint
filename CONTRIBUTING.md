# Contributing to Waypoint

## Getting Started

1. Fork and clone the repo
2. Read the [docs/](docs/) to understand the product and architecture
3. Pick an issue or check [docs/build-order.md](docs/build-order.md) for what's next

## Project Structure

- `frontend/` -- Next.js app
- `backend/` -- FastAPI app
- `docs/` -- project documentation (product, architecture, data model, etc.)

## Development

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

## Code Standards

- Write clear, self-documenting code over clever one-liners
- No comments unless explaining _why_, not _what_
- Every bug fix includes a regression test
- Pin dependencies to specific versions

## Branch and PR Workflow

1. Create a feature branch from `main`
2. Keep PRs small and focused -- one feature or fix per PR
3. Write a clear PR title and description
4. Ensure all tests pass before requesting review

## Commit Messages

Use short, imperative-style messages:

```
Add JWT login endpoint
Fix issue matching threshold
Update dashboard task table columns
```

## Architecture Decisions

Before making significant changes to the architecture, data model, or AI stack, open an issue to discuss the approach first. See the relevant doc for context:

- [docs/architecture.md](docs/architecture.md) -- tech stack and structure
- [docs/data-model.md](docs/data-model.md) -- task model and statuses
- [docs/ai-stack.md](docs/ai-stack.md) -- models, rate limits, caching

## Key Constraints

- **Waypoint never writes to GitHub.** All GitHub interaction is read-only.
- **The agent proposes, the PM approves.** No automated actions without PM confirmation.
- **Per-account API keys.** Each PM provides their own Gemini key. Never share or pool keys.
