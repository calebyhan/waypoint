"""Single source of truth for turning GitHub issue/PR payloads into rows and
task-status transitions. Both the webhook handler and the reconcile poller
call into this module so there's exactly one upsert and one state-machine
implementation instead of two copies that can drift.
"""

import logging

from supabase import Client

from services.matching import match_issue_to_task, match_pr_to_task

logger = logging.getLogger(__name__)


async def upsert_issue(db: Client, workspace_id: str, issue: dict) -> dict:
    """Atomic upsert keyed on (workspace_id, github_id)."""
    row = {
        "workspace_id": workspace_id,
        "github_id": issue["id"],
        "number": issue["number"],
        "title": issue["title"],
        "state": issue["state"],
        "body": issue.get("body"),
        "html_url": issue.get("html_url"),
        "github_updated_at": issue.get("updated_at"),
    }
    result = db.table("github_issues").upsert(row, on_conflict="workspace_id,github_id").execute()
    return result.data[0]


async def upsert_pr(db: Client, workspace_id: str, pr: dict) -> dict:
    """Atomic upsert keyed on (workspace_id, github_id)."""
    row = {
        "workspace_id": workspace_id,
        "github_id": pr["id"],
        "number": pr["number"],
        "title": pr["title"],
        "state": pr["state"],
        "merged": pr.get("merged", pr.get("merged_at") is not None),
        "html_url": pr.get("html_url"),
        "github_updated_at": pr.get("updated_at"),
    }
    result = db.table("github_prs").upsert(row, on_conflict="workspace_id,github_id").execute()
    return result.data[0]


def _linked_task(db: Client, github_issue_id: str) -> dict | None:
    result = db.table("tasks").select("*").eq("github_issue_id", github_issue_id).execute()
    return result.data[0] if result.data else None


def bump_task(db: Client, task_id: str, updates: dict) -> dict | None:
    """Update a task and increment its optimistic-concurrency version.

    All GitHub-driven writes to `tasks` (webhook/reconcile status transitions,
    write-back bookkeeping, proposal accept/unlink/conflict-resolution) go
    through this instead of a bare `.update()`, so a human's next
    version-checked PATCH (projects.py's update_task) correctly detects that
    the row changed underneath them instead of silently permitting a stomp.
    """
    current = db.table("tasks").select("version").eq("id", task_id).single().execute().data
    payload = dict(updates)
    if current and current.get("version") is not None:
        payload["version"] = current["version"] + 1
    result = db.table("tasks").update(payload).eq("id", task_id).execute()
    return result.data[0] if result.data else None


async def handle_issue_change(
    db: Client,
    workspace: dict,
    saved_issue: dict,
    action: str,
    gemini_key: str | None,
    *,
    is_new: bool,
) -> None:
    """Centralizes issue-driven side effects: matching triggers and status transitions."""
    if action == "deleted":
        db.table("github_issues").update({"state": "deleted"}).eq("id", saved_issue["id"]).execute()
        return

    task = _linked_task(db, saved_issue["id"])

    if (is_new or action in ("opened", "reopened")) and task is None:
        await match_issue_to_task(db, workspace["id"], saved_issue, gemini_key)

    if task is not None and saved_issue["state"] in ("closed", "open"):
        recompute_task_done_state(db, task["id"])


async def handle_pr_change(
    db: Client,
    workspace: dict,
    saved_pr: dict,
    action: str,
    gemini_key: str | None,
    *,
    is_new: bool,
) -> None:
    """Centralizes PR-driven side effects: matching triggers and status transitions."""
    if is_new or action == "opened":
        proposal = await match_pr_to_task(db, workspace["id"], saved_pr, gemini_key)
        if proposal and proposal.get("task_id"):
            bump_task(db, proposal["task_id"], {"status": "in_review"})
        return

    if saved_pr.get("linked_task_id") and action in ("closed", "reopened"):
        recompute_task_done_state(db, saved_pr["linked_task_id"])


def recompute_task_done_state(db: Client, task_id: str) -> None:
    """Bidirectionally reconcile a task's status against its linked issue/PR state.

    Replaces the old one-directional, additive-only `_maybe_mark_done`: this
    also handles issue-reopened and PR-closed-unmerged reversals.

    Called from GitHub-driven events (webhook/reconcile) -- GitHub's open/closed
    state always wins here per the field-owner-split rule. The one real
    collision case (a task explicitly marked done in Waypoint while its issue
    is independently open on GitHub) is detected separately, at the moment of
    that Waypoint-initiated write, in dashboard.py's update_task_status -- not
    here, since by the time this function runs from a GitHub event, GitHub's
    state is authoritative and there's nothing ambiguous left to flag.
    """
    task = db.table("tasks").select("*").eq("id", task_id).single().execute().data
    if not task:
        return

    issue = None
    if task.get("github_issue_id"):
        issue = db.table("github_issues").select("*").eq("id", task["github_issue_id"]).single().execute().data

    prs = db.table("github_prs").select("merged, state").eq("linked_task_id", task_id).execute().data or []
    pr_merged = any(p["merged"] for p in prs)
    pr_open_unmerged = any(p["state"] == "closed" and not p["merged"] for p in prs) and not pr_merged

    issue_closed = issue is not None and issue["state"] == "closed"
    issue_open = issue is not None and issue["state"] == "open"

    if issue_closed and (pr_merged or not prs):
        if task["status"] != "done":
            bump_task(db, task_id, {"status": "done", "github_conflict": False})
        return

    if issue_open and task["status"] == "done":
        bump_task(db, task_id, {"status": "open", "github_conflict": False})
        return

    if pr_open_unmerged and task["status"] == "in_review":
        bump_task(db, task_id, {"status": "open"})
