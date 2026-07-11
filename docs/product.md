# Product

## Problem

Turning a PRD into a working project plan is slow, inconsistent, and usually done poorly. Most PM tools are either too heavy (Jira) or too passive (Notion). Small teams need something that does the thinking -- scoping, decomposing, tracking -- without getting in the way.

## Target User

- **Primary:** Project managers at small engineering teams (2-10 people)
- **Not:** Individual developers, non-technical PMs, enterprise orgs

## Core Principles

- **Propose, don't act** -- the agent's own suggestions (plan decompositions, re-ingestion diffs, issue/PR match proposals) always require PM approval before anything changes. The PM's direct edits are different: they apply immediately, and Waypoint syncs them to GitHub on the PM's behalf.
- **Bidirectional GitHub sync** -- GitHub is the source of truth for issue and PR state. Waypoint listens for and reconciles GitHub signals, and writes back to keep each task's linked issue in sync: it creates an issue when a task is created in Waypoint, pushes title/description edits, and closes/reopens the issue when the task crosses the `done` boundary (see `docs/github-integration.md`). Waypoint never creates PRs or milestones, and never edits GitHub content that isn't linked to a Waypoint task.
- **Free to use** -- built on free-tier infrastructure, sustainable at low cost
- **New projects only** -- no importing existing repos or issue history in v1

## User Flow

```
1.  PM creates a workspace (one project per workspace)
2.  PM drops in a PRD, spec doc, or rough notes
3.  Agent asks <= 3 clarifying questions (deadline, team size, tech stack)
4.  Agent proposes epics + PR-sized tasks
5.  PM edits, merges, deletes, reorders tasks in the proposal view
6.  PM approves the plan
7.  PM configures a GitHub webhook in their repo pointing at Waypoint's endpoint
8.  Tasks the PM creates in Waypoint get GitHub issues created for them automatically;
    issues the team creates directly on GitHub are detected via webhook + semantic matching
9.  Agent proposes issue-task links for GitHub-originated issues, PM confirms with one click
10. Dashboard tracks progress via GitHub signals; PM can manually override task status
11. Task edits and done/reopen status changes sync back to the linked GitHub issue
```

## The Three Screens

### 1. Ingest

- Paste text or upload a PDF (URL ingestion is planned, not yet implemented)
- Agent reads the document and asks up to 3 clarifying questions:
  - What is the deadline?
  - How many people are on the team?
  - What is the tech stack?
- Generates a proposed epic/task tree

### 2. Proposal View

- Epics displayed as collapsible sections
- Tasks displayed as editable cards, each showing:
  - Title
  - Description
  - Estimated days
  - Priority (p0 / p1 / p2 -- agent proposes, PM overrides)
  - Dependencies (used for blocker warnings on the dashboard)
- PM can edit, merge, split, delete, or reorder tasks inline
- Nothing is committed until the PM clicks **Approve Plan**

### 3. Dashboard

- Milestone progress bars (% of tasks done per epic)
- Task table with: assignee, status, linked GitHub issue, linked PR, days open
- Agent insight strip: surfaces blockers, dependency violations, stale PRs, unassigned tasks, partial done signals (sorted by task priority)
- Manual assignee picker per task row
- Task scheduling: each task gets a computed `start_date`/`end_date` from a dependency- and assignee-aware, weekday-only scheduler; the PM can reschedule the whole plan with a project start date, a per-member weekly ticket pacing limit, and a preferred start weekday
- GitHub conflict resolution: when Waypoint's task status and GitHub's issue state disagree (e.g. task marked done while the issue is still open), the dashboard flags the conflict and the PM picks which side wins

### Auxiliary Screens

- **Login** (`/login`) -- GitHub OAuth sign-in
- **Onboarding** (`/onboarding`) -- first-run profile setup (Gemini API key)
- **Workspaces list** (`/workspaces`) -- create/select/archive workspaces
- **Workspace setup** (`/workspaces/[id]/setup`) -- connect a GitHub repo, view the webhook URL/secret
- **Workspace settings** (`/workspaces/[id]/settings`) -- team roster, member roles/invites, scheduling config
- **Global settings** (`/settings`) -- Gemini API key management
- **Re-ingest** (`/workspaces/[id]/reingest`) -- PRD diff review flow described in `docs/agent-behaviors.md`

## Planned / Not Yet Implemented

- **URL ingestion** -- pasting a URL as a PRD source on the Ingest screen
- **Scope-gap detection** -- surfacing areas of the PRD not covered by any task in the insight strip
- **Label-based issue matching** -- see `docs/github-integration.md`
- **Presence indicator** -- showing which PMs are currently viewing a workspace
