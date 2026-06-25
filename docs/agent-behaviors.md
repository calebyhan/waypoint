# Agent Behaviors

## Trigger-Action Table

| Trigger | Agent Action |
|---|---|
| PRD uploaded | Decompose into epics + PR-sized tasks |
| Ambiguous scope | Ask clarifying question (max 3) |
| GitHub issue created | Run matching pipeline, propose link to PM |
| PR opened referencing an issue | Update task status to `in_review` |
| PR merged + issue closed | Mark task as `done` |
| Task open >3 days with no PR | Surface as blocker on dashboard |
| PRD re-ingested | Diff against existing plan, propose changes |
| Scope gap detected | Propose new tasks, require PM approval |
| Reconciliation poll (every 15 min) | Read GitHub issues/PRs, reconcile missed webhook events |
| Partial done signal | Surface warning to PM, allow manual override |

## Insight Strip

The dashboard includes an agent insight strip that surfaces actionable warnings, sorted by task priority (p0 first):

- **Blockers** -- tasks open >3 days with no linked PR
- **Dependency violations** -- tasks in progress whose dependencies aren't done
- **Stale PRs** -- PRs open for an extended period without merging
- **Unassigned tasks** -- tasks with no assignee
- **Scope gaps** -- areas of the PRD not covered by any task

## PRD Re-ingestion

When a PRD changes mid-project, the PM can re-ingest the updated document. The agent diffs the new decomposition against the existing plan:

```
New PRD → agent decomposes → diff against existing tasks
  → "3 tasks unchanged, 2 modified, 1 new, 1 removed"
  → PM reviews diff and approves changes
```

For modified tasks already linked to a GitHub issue, the agent flags specifically:

> _"Task 'JWT refresh' changed scope -- it's linked to issue #42. The issue description may be outdated."_

The PM updates the GitHub issue manually in their own workflow. Waypoint never writes to GitHub.
