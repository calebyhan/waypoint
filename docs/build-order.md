# Build Order

## Phases

| Phase | What | Depends On |
|---|---|---|
| 1 | GitHub OAuth + repo connection | -- |
| 2 | Ingest + decomposition (core AI loop) | Phase 1 (need auth for API key storage) |
| 3 | Proposal UI (edit/approve flow) | Phase 2 (need decomposition output to display) |
| 4 | Webhook listener + smart matching | Phase 1 (need repo access), Phase 3 (need approved tasks to match against) |
| 5 | Dashboard + real-time updates | Phase 4 (need linked issues/PRs to track) |
| 6 | PRD diff / re-ingestion | Phase 3 (need existing plan to diff against) |
| 7 | Agent insight strip | Phase 5 (need dashboard context to surface insights) |

## Out of Scope (v1)

- Creating or modifying GitHub pull requests or milestones (issue write-back for Waypoint-managed tasks IS in scope -- Waypoint creates, edits, and closes/reopens the issues linked to its tasks; see `docs/github-integration.md`)
- Importing existing projects or repos
- A dedicated developer-facing product surface (developers and stakeholders CAN log in when invited as workspace members with the `member` role -- see `docs/data-model.md` -- but there is no separate developer UI)
- Slack or other integrations
- Mobile app
- Linear, Jira, or Notion support

## v2 Candidates

- Velocity tracking over time (are estimates accurate?)
- Exportable reports for stakeholders
- Slack digest integration
- Multi-project support per workspace
