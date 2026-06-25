# Product

## Problem

Turning a PRD into a working project plan is slow, inconsistent, and usually done poorly. Most PM tools are either too heavy (Jira) or too passive (Notion). Small teams need something that does the thinking -- scoping, decomposing, tracking -- without getting in the way.

## Target User

- **Primary:** Project managers at small engineering teams (2-10 people)
- **Not:** Individual developers, non-technical PMs, enterprise orgs

## Core Principles

- **Propose, don't act** -- the agent always proposes, the PM always approves before anything changes
- **GitHub is the source of truth** -- Waypoint reads and listens, never writes
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
8.  PM creates GitHub issues manually in their own workflow
9.  Waypoint detects new issues via webhook + semantic matching
10. Agent proposes issue-task links, PM confirms with one click
11. Dashboard tracks progress via GitHub signals; PM can manually override task status
```

## The Three Screens

### 1. Ingest

- Paste text, upload a PDF/doc, or paste a URL
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
- Agent insight strip: surfaces blockers, dependency violations, stale PRs, unassigned tasks, scope gaps (sorted by task priority)
- Manual assignee picker per task row
- PM sets milestone deadlines and team size directly on the dashboard
