import logging
from datetime import datetime, timedelta, timezone

import httpx
from supabase import Client

from services.matching import match_issue_to_task, match_pr_to_task

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
RECONCILE_WINDOW_MINUTES = 20


async def reconcile_all_workspaces(db: Client):
    """Poll GitHub for missed issue/PR events across all active, connected workspaces."""
    workspaces = (
        db.table("workspaces")
        .select("*")
        .eq("state", "active")
        .not_.is_("repo_owner", "null")
        .execute()
    )
    for workspace in workspaces.data:
        try:
            await _reconcile_workspace(db, workspace)
        except Exception:
            logger.exception("Reconciliation failed for workspace %s", workspace["id"])


async def _reconcile_workspace(db: Client, workspace: dict):
    profile = db.table("profiles").select("gemini_api_key").eq("id", workspace["owner_id"]).single().execute()
    gemini_key = profile.data.get("gemini_api_key") if profile.data else None

    token = _get_github_token(db, workspace["owner_id"])
    if not token:
        return

    since = (datetime.now(timezone.utc) - timedelta(minutes=RECONCILE_WINDOW_MINUTES)).isoformat()
    owner, name = workspace["repo_owner"], workspace["repo_name"]

    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

        issues_resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{name}/issues",
            headers=headers,
            params={"since": since, "state": "all"},
        )
        if issues_resp.status_code == 200:
            for issue in issues_resp.json():
                if "pull_request" in issue:
                    continue
                await _upsert_issue(db, workspace, issue, gemini_key)

        pulls_resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{name}/pulls",
            headers=headers,
            params={"state": "all", "sort": "updated", "direction": "desc"},
        )
        if pulls_resp.status_code == 200:
            for pr in pulls_resp.json():
                updated_at = datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))
                if updated_at < datetime.now(timezone.utc) - timedelta(minutes=RECONCILE_WINDOW_MINUTES):
                    continue
                await _upsert_pr(db, workspace, pr, gemini_key)


async def _upsert_issue(db: Client, workspace: dict, issue: dict, gemini_key: str | None):
    row = {
        "workspace_id": workspace["id"],
        "github_id": issue["id"],
        "number": issue["number"],
        "title": issue["title"],
        "state": issue["state"],
    }
    existing = (
        db.table("github_issues")
        .select("*")
        .eq("workspace_id", workspace["id"])
        .eq("github_id", issue["id"])
        .execute()
    )
    if existing.data:
        result = db.table("github_issues").update(row).eq("id", existing.data[0]["id"]).execute()
        saved = result.data[0]
        if issue["state"] == "closed" and saved.get("linked_task_id"):
            _maybe_mark_done(db, saved["linked_task_id"])
    else:
        result = db.table("github_issues").insert(row).execute()
        saved = result.data[0]
        if issue["state"] == "open":
            await match_issue_to_task(db, workspace["id"], saved, gemini_key)


async def _upsert_pr(db: Client, workspace: dict, pr: dict, gemini_key: str | None):
    row = {
        "workspace_id": workspace["id"],
        "github_id": pr["id"],
        "number": pr["number"],
        "title": pr["title"],
        "state": pr["state"],
        "merged": pr.get("merged_at") is not None,
    }
    existing = (
        db.table("github_prs")
        .select("*")
        .eq("workspace_id", workspace["id"])
        .eq("github_id", pr["id"])
        .execute()
    )
    if existing.data:
        result = db.table("github_prs").update(row).eq("id", existing.data[0]["id"]).execute()
        saved = result.data[0]
        if row["merged"] and saved.get("linked_task_id"):
            _maybe_mark_done(db, saved["linked_task_id"])
    else:
        result = db.table("github_prs").insert(row).execute()
        saved = result.data[0]
        proposal = await match_pr_to_task(db, workspace["id"], saved, gemini_key)
        if proposal and proposal.get("task_id"):
            db.table("tasks").update({"status": "in_review"}).eq("id", proposal["task_id"]).execute()


def _maybe_mark_done(db: Client, task_id: str):
    issues = db.table("github_issues").select("state").eq("linked_task_id", task_id).execute()
    prs = db.table("github_prs").select("merged").eq("linked_task_id", task_id).execute()
    issue_closed = all(i["state"] == "closed" for i in issues.data) if issues.data else False
    pr_merged = any(p["merged"] for p in prs.data) if prs.data else False
    if issue_closed and pr_merged:
        db.table("tasks").update({"status": "done"}).eq("id", task_id).execute()


def _get_github_token(db: Client, user_id: str) -> str | None:
    try:
        result = db.auth.admin.get_user_by_id(user_id)
        for identity in result.user.identities or []:
            if identity.provider == "github":
                return identity.identity_data.get("provider_token")
    except Exception:
        logger.exception("Failed to fetch GitHub token for user %s", user_id)
    return None
