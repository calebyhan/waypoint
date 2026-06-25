# Data Model

## Hierarchy

```
Project
  └── Epic (feature grouping)
        └── Task (PR-sized)
              ├── GitHub Issue (linked via webhook matching)
              ├── GitHub PR (linked when opened)
              ├── Assignee (set manually)
              ├── Priority (p0 / p1 / p2)
              ├── Estimated days
              ├── Dependencies (list of task IDs)
              └── Status: open → in_review → done (PM can override manually)
```

## Tasks

- **Granularity:** PR-sized -- 1 to 2 days of work per task
- **Assignment:** Manual, by PM on the dashboard
- **Done state:** GitHub issue closed AND PR merged to main (both signals expected). PM can manually mark a task done if signals are incomplete.

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
| `done` | Issue closed + PR merged (or PM manual override) |

The PM can manually set any status at any time to handle edge cases (e.g., PR merged without closing the issue).

## Dependencies

Dependencies are tracked as soft constraints -- they don't block work, but the dashboard surfaces warnings when ordering is violated:

> _"Task 'Add refresh endpoint' is in progress, but its dependency 'Set up auth middleware' is still open."_

The agent proposes dependencies during decomposition. The PM can add, remove, or ignore them.

## Workspace Lifecycle

- **One project per workspace**
- **Multiple PMs** can log in to the same workspace
- Developers do not log in -- Waypoint is PM-facing only
- Auth via GitHub OAuth (covers login + repo access in one flow)

### States

| State | Behavior |
|---|---|
| Active | Default. Full read/write access to the project. |
| Archived | Read-only. Hidden from the default workspace list. |
| Deleted | Permanently removed. Not recoverable. |

PM can archive a completed workspace, restore an archived workspace, or permanently delete it.

### Multi-PM Editing

When multiple PMs are in the same workspace, the proposal view and dashboard use optimistic locking:

- Each save carries a version number; if another PM saved first, the second PM sees a conflict notification with the option to reload and re-apply their changes
- A lightweight presence indicator shows which PMs are currently viewing the workspace
