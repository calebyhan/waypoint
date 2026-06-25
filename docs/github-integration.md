# GitHub Integration

Waypoint reads from GitHub only -- it never creates or modifies issues, PRs, or milestones.

## Setup

The PM configures a GitHub webhook in their repo settings, pointing at Waypoint's endpoint (`POST /webhooks/github`). Waypoint provides the URL and a generated secret during workspace setup.

## Webhook Events

| Event | What Waypoint Does |
|---|---|
| `issues.opened` | Run issue matching pipeline, propose link to task |
| `issues.closed` | Check if linked task should be marked done |
| `pull_request.opened` | Run PR matching pipeline, update task status to `in_review` |
| `pull_request.merged` | Check if linked task should be marked done |

## Reconciliation Polling

Webhooks are fire-and-forget -- missed events (cold starts, downtime) cause silent data loss. A scheduled polling job runs every 15 minutes via the GitHub API to reconcile state:

- `GET /repos/{owner}/{repo}/issues?since=...`
- `GET /repos/{owner}/{repo}/pulls?since=...`

This is read-only and ensures no event is permanently missed.

## Issue Matching Pipeline

When a GitHub issue is created:

```
1. Fuzzy title match     → issue title closely matches a task title
2. Semantic match        → cosine similarity of embeddings above threshold
3. Label match           → issue label maps to an epic
4. Fallback              → surface as "unlinked issue", PM confirms manually
```

The agent proposes the match via a confirmation toast:

> _"New issue #42 'Add JWT refresh logic' -- link to task 'Implement token refresh'? Yes / No"_

One click. Never interrupts the PM's GitHub workflow.

## PR Matching Pipeline

When a pull request is opened:

```
1. Issue reference match → parse "Fixes #N" / "Closes #N" from PR body/title
                           → map to the already-linked issue → map to the task
2. Semantic fallback     → if no issue reference, run fuzzy/embedding match
                           against task titles using PR title + branch name
3. Fallback              → surface as "unlinked PR", PM confirms manually
```

The agent proposes the match the same way:

> _"PR #55 'jwt-refresh-endpoint' -- link to task 'Implement token refresh'? Yes / No"_

## Partial Signal Handling

When GitHub signals are incomplete (e.g., PR merged but issue still open, or issue closed without a PR), the dashboard surfaces a warning:

> _"PR #55 merged but issue #42 still open -- is this task done?"_

The PM can manually mark the task as done. GitHub remains the source of signals, but the PM is the source of truth for status.
