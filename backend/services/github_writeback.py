"""Pushes Waypoint task edits back to GitHub. The Waypoint-side DB write has
already committed by the time these are called, so a GitHub failure here must
never raise back to the caller -- it gets queued in github_write_outbox for
the drain job to retry instead.
"""

import logging
from datetime import datetime, timezone

import httpx
from supabase import Client

from services.github import create_issue, update_issue
from services.github_sync import bump_task

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 10


async def create_issue_for_task(db: Client, workspace: dict, task: dict, token: str) -> None:
    """Create a GitHub issue for a newly created task with no linked issue yet."""
    body = task.get("description")
    try:
        issue = await create_issue(token, workspace["repo_owner"], workspace["repo_name"], task["title"], body)
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        _queue_outbox(db, workspace["id"], task["id"], "create_issue", {"title": task["title"], "body": body}, str(e))
        return

    saved_issue = (
        db.table("github_issues")
        .insert({
            "workspace_id": workspace["id"],
            "github_id": issue["id"],
            "number": issue["number"],
            "title": issue["title"],
            "state": issue["state"],
            "body": issue.get("body"),
            "html_url": issue.get("html_url"),
            "github_updated_at": issue.get("updated_at"),
            "waypoint_updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .execute()
        .data[0]
    )
    bump_task(db, task["id"], {
        "github_issue_id": saved_issue["id"],
        "github_synced_at": datetime.now(timezone.utc).isoformat(),
    })


async def update_issue_for_task(db: Client, workspace: dict, task: dict, token: str) -> None:
    """Push a task's title/description to its already-linked GitHub issue."""
    issue = db.table("github_issues").select("*").eq("id", task["github_issue_id"]).single().execute().data
    if not issue:
        return
    try:
        updated = await update_issue(
            token, workspace["repo_owner"], workspace["repo_name"], issue["number"],
            title=task["title"], body=task.get("description"),
        )
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        _queue_outbox(
            db, workspace["id"], task["id"], "update_issue",
            {"issue_number": issue["number"], "title": task["title"], "body": task.get("description")}, str(e),
        )
        return

    now = datetime.now(timezone.utc).isoformat()
    db.table("github_issues").update({
        "title": updated["title"],
        "body": updated.get("body"),
        "waypoint_updated_at": now,
    }).eq("id", issue["id"]).execute()
    bump_task(db, task["id"], {"github_synced_at": now})


async def sync_task_status_to_github(db: Client, workspace: dict, task: dict, token: str, *, close: bool) -> None:
    """Push a done/open boundary crossing to the linked issue's open/closed state."""
    issue = db.table("github_issues").select("*").eq("id", task["github_issue_id"]).single().execute().data
    if not issue:
        return
    new_state = "closed" if close else "open"
    try:
        updated = await update_issue(
            token, workspace["repo_owner"], workspace["repo_name"], issue["number"], state=new_state,
        )
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        kind = "close_issue" if close else "reopen_issue"
        _queue_outbox(db, workspace["id"], task["id"], kind, {"issue_number": issue["number"]}, str(e))
        return

    db.table("github_issues").update({
        "state": updated["state"],
        "waypoint_updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", issue["id"]).execute()


def _queue_outbox(db: Client, workspace_id: str, task_id: str, kind: str, payload: dict, error: str) -> None:
    logger.warning("Queuing GitHub write-back retry for task %s (%s): %s", task_id, kind, error)
    db.table("github_write_outbox").insert({
        "workspace_id": workspace_id,
        "task_id": task_id,
        "kind": kind,
        "payload": payload,
        "attempts": 1,
        "last_error": error,
    }).execute()


async def drain_outbox(db: Client) -> None:
    """Retry pending outbox rows; gives up (marks completed with the last error) after MAX_ATTEMPTS."""
    from services.github import get_github_token

    pending = db.table("github_write_outbox").select("*").is_("completed_at", "null").execute().data or []
    for row in pending:
        workspace = db.table("workspaces").select("*").eq("id", row["workspace_id"]).single().execute().data
        if not workspace or not workspace.get("repo_owner"):
            continue
        token = get_github_token(db, workspace["owner_id"])
        if not token:
            continue

        try:
            await _retry_one(db, workspace, row, token)
            db.table("github_write_outbox").update({
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", row["id"]).execute()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            attempts = row["attempts"] + 1
            updates = {"attempts": attempts, "last_error": str(e)}
            if attempts >= MAX_ATTEMPTS:
                updates["completed_at"] = datetime.now(timezone.utc).isoformat()
                bump_task(db, row["task_id"], {"github_sync_error": str(e)})
            db.table("github_write_outbox").update(updates).eq("id", row["id"]).execute()


async def _retry_one(db: Client, workspace: dict, row: dict, token: str) -> None:
    payload = row["payload"]
    if row["kind"] == "create_issue":
        task = db.table("tasks").select("*").eq("id", row["task_id"]).single().execute().data
        if task and not task.get("github_issue_id"):
            await create_issue_for_task(db, workspace, task, token)
    elif row["kind"] == "update_issue":
        await update_issue(
            token, workspace["repo_owner"], workspace["repo_name"], payload["issue_number"],
            title=payload.get("title"), body=payload.get("body"),
        )
    elif row["kind"] in ("close_issue", "reopen_issue"):
        state = "closed" if row["kind"] == "close_issue" else "open"
        await update_issue(token, workspace["repo_owner"], workspace["repo_name"], payload["issue_number"], state=state)
