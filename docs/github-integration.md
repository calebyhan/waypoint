# GitHub Integration

Waypoint syncs bidirectionally with GitHub issues. Inbound, it listens to webhooks and polls the GitHub API to reconcile issue/PR activity into the plan. Outbound, it writes task changes back to GitHub: creating an issue when a task is created in Waypoint, pushing title/description edits to the linked issue, and closing/reopening the issue when the task crosses the `done` boundary (see [Write-Back Behavior](#write-back-behavior)). Waypoint never creates or modifies pull requests or milestones, and never edits GitHub content that isn't linked to a Waypoint task.

## Setup

The PM configures a GitHub webhook in their repo settings, pointing at Waypoint's endpoint (`POST /webhooks/github`). Waypoint provides the URL and a generated secret during workspace setup.

## Webhook Events

| Event | What Waypoint Does |
|---|---|
| `issues.opened` | Run issue matching pipeline, propose link to task |
| `issues.closed` | Check if linked task should be marked done |
| `pull_request.opened` | Run PR matching pipeline, propose link to task; task moves to `in_review` when the PM accepts |
| `pull_request.merged` | Check if linked task should be marked done |

## Reconciliation Polling

Webhooks are fire-and-forget -- missed events (cold starts, downtime) cause silent data loss. A scheduled polling job runs every 15 minutes via the GitHub API to reconcile state:

- `GET /repos/{owner}/{repo}/issues?since=...`
- `GET /repos/{owner}/{repo}/pulls?since=...`

The polling itself is read-only and ensures no inbound event is permanently missed.

## Write-Back Behavior

When a workspace has a connected repo, Waypoint pushes task changes to GitHub (`backend/services/github_writeback.py`):

| Waypoint action | GitHub write |
|---|---|
| Task created in Waypoint | `create_issue_for_task` -- creates a new issue with the task's title/description and links it (`tasks.github_issue_id`, enforced 1:1) |
| Task title/description edited (task has a linked issue) | `update_issue_for_task` -- pushes the new title/body to the issue |
| Task status crosses the `done` boundary on the dashboard | `sync_task_status_to_github` -- closes the issue on `done`, reopens it when the PM reverts a done task |

Notes:

- Writes are best-effort and never block the PM: the Waypoint-side save has already committed, so a GitHub failure (rate limit, timeout) is queued in the `github_write_outbox` table instead of raising.
- A scheduled drain job (`core/scheduler.py`, every 2 minutes) retries pending outbox rows. After `MAX_ATTEMPTS = 10` failed attempts the row is marked completed with its last error, and the error is recorded on the task (`github_sync_error`).
- Marking a task done while its linked issue is still open on GitHub does **not** silently close the issue -- it flags a conflict (`github_conflict` / `github_conflict_reason`) that the PM resolves explicitly via `POST /tasks/{id}/resolve-conflict` (`keep_waypoint` re-pushes Waypoint's status and closes the issue; `keep_github` reverts the task to `open`).
- Unlinking a task from an issue/PR only clears Waypoint's pointer -- it never deletes or edits anything on GitHub.
- Waypoint never writes to pull requests or milestones.

## Issue Matching Pipeline

When a GitHub issue is created:

```
1. Fuzzy title match     → issue title closely matches a task title
2. Semantic match        → cosine similarity of embeddings above threshold
3. Fallback              → surface as "unlinked issue", PM confirms manually
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

## Planned / Not Yet Implemented

- **Label-based issue matching** -- mapping an issue label to an epic as an additional matching signal. The pipeline currently uses fuzzy title match and semantic (embedding) match only.
