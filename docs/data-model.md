# Data Model

## Hierarchy

```
Project
  └── Epic (feature grouping)
        └── Task (PR-sized)
              ├── GitHub Issue (github_issue_id -- enforced 1:1, linked via
              │     webhook matching or created by Waypoint's write-back)
              ├── GitHub PR (linked when opened; many PRs may link one task)
              ├── Assignee (set manually)
              ├── Priority (p0 / p1 / p2)
              ├── Estimated days
              ├── Dependencies (list of task IDs)
              ├── Ticket detail: motivation (string), deliverables (string[]),
              │     important_notes (string[])
              ├── Schedule: start_date / end_date (computed by the scheduler,
              │     PM-editable)
              ├── GitHub sync bookkeeping: github_synced_at, github_conflict,
              │     github_conflict_reason, github_sync_error
              ├── version (optimistic-lock counter)
              └── Status: open → in_review → done (PM can override manually)
```

## Tasks

- **Granularity:** PR-sized -- 1 to 2 days of work per task
- **Assignment:** Manual, by PM on the dashboard
- **Done state:** GitHub issue closed, with a merged PR when one exists -- if the task has no linked PR at all, a closed issue alone is sufficient. PM can manually mark a task done at any time, or manually revert it if GitHub signals are incomplete or contradictory (see `github_conflict` handling in `docs/github-integration.md`).
- **Ticket detail:** each task carries optional `motivation` (why the work matters), `deliverables` (concrete outputs), and `important_notes` (gotchas/constraints), populated by the AI during decomposition and editable by the PM.

## Priority

Tasks are assigned a priority level:

| Level | Meaning |
|---|---|
| p0 | Launch blocker -- must be done |
| p1 | Important -- should be done |
| p2 | Nice to have -- can be cut |

The agent proposes initial priorities during decomposition. The PM can override at any time. The dashboard insight strip sorts warnings by priority so blockers on p0 tasks surface first.

## Status Lifecycle

```
open → in_review → done
```

| Status | Triggered by |
|---|---|
| `open` | Task created during plan approval |
| `in_review` | PR opened and linked to the task |
| `done` | Issue closed (+ PR merged when one exists), or PM manual override |

The PM can manually set any status at any time to handle edge cases (e.g., PR merged without closing the issue).

Status changes that cross the `done` boundary sync back to GitHub: marking a task done closes its linked issue, and reverting a done task reopens it. If the linked issue is still open on GitHub when the PM marks the task done, Waypoint flags a conflict (`github_conflict` / `github_conflict_reason`) instead of silently closing the issue, and the PM resolves it explicitly (keep Waypoint's status, or keep GitHub's). See `docs/github-integration.md#write-back-behavior`.

## Dependencies

Dependencies are tracked as soft constraints -- they don't block work, but the dashboard surfaces warnings when ordering is violated:

> _"Task 'Add refresh endpoint' is in progress, but its dependency 'Set up auth middleware' is still open."_

The agent proposes dependencies during decomposition. The PM can add, remove, or ignore them. Dependencies also feed the scheduler: a task is never scheduled to start before its dependencies end.

## Task Scheduling

Every task carries a computed `start_date` and `end_date` (`services/scheduling.py`). The scheduler:

- Orders tasks topologically by dependencies; a task starts no earlier than the weekday after its last dependency ends
- Schedules on weekdays only, using `estimated_days` as the duration
- Serializes each assignee's tasks (one at a time per person)
- Optionally paces new-ticket starts per assignee via workspace config:
  - `tickets_per_member_per_week` -- max tickets a member starts per week (0 = no pacing, back-to-back)
  - `assign_day` -- preferred start weekday for new tickets, 0=Mon..4=Fri (-1 = no preference; only applied when pacing is active)
  - `schedule_start_date` -- the project start date

The PM can edit an individual task's dates/assignee (`PATCH /tasks/{id}/schedule`) or re-run the scheduler across the whole workspace (`POST /reschedule`), which persists the scheduling config on the workspace.

## Team Roster

Separate from platform accounts, each workspace has a `team_members` roster used for planning:

- **Fields:** `name`, `role` (one of `frontend`, `backend`, `fullstack`, `devops`, `design`, `qa`, `pm` -- a job-function label, not a permission), `weekly_capacity_hours` (default 40), and an optional `user_id` link to a real workspace member's account once that person has joined
- **Used by:** AI decomposition (task assignment suggestions in `services/ai.py`) and scheduler pacing
- Managed on the workspace settings screen; the ingest wizard can bulk-replace the roster (`PUT /team/sync`)

## Workspace Lifecycle

- **One project per workspace**
- **Multiple people** can log in to the same workspace, with per-workspace roles (see below)
- Auth via GitHub OAuth (covers login + repo access in one flow)

### Roles & Invites

Each `workspace_members` row carries a permission role (distinct from the team roster's job-function role):

| Role | Who | Permissions |
|---|---|---|
| `owner` | The workspace creator | Everything. Cannot be demoted or removed. |
| `pm` | Co-managers | Manage members, invites, team roster, and the plan. |
| `member` | Invited collaborators (developers, stakeholders) | Baseline access -- can log in and view the workspace, members, and roster. |

Endpoints enforce a minimum role via `backend/core/permissions.py` (`member < pm < owner`).

Invites are keyed by GitHub username (auth is GitHub-OAuth-only): a PM or owner creates a `workspace_invites` row with a target role (`pm` or `member`), and the invite is auto-accepted the next time that GitHub user logs in (`backend/routers/auth.py`). Pending invites can be revoked; one pending invite per username per workspace.

### States

| State | Behavior |
|---|---|
| Active | Default. Full read/write access to the project. |
| Archived | Read-only. Hidden from the default workspace list. |
| Deleted | Permanently removed. Not recoverable. |

PM can archive a completed workspace, restore an archived workspace, or permanently delete it.

### Multi-PM Editing

When multiple PMs are in the same workspace, the proposal view and dashboard use optimistic locking:

- Each save carries a version number (`tasks.version`); if another PM saved first, the second PM gets a `409` conflict with the option to reload and re-apply their changes
- A lightweight presence indicator showing which PMs are currently viewing the workspace is planned (not yet implemented)

## AI Usage Logging

Every Gemini call made during ingest/decomposition is logged to the `ai_usage` table (`user_id`, `workspace_id`, `model`, `tokens_in`, `tokens_out`, `created_at`). This is the cost-tracking mechanism behind the free-tier sustainability principle; users can read their own usage rows.
