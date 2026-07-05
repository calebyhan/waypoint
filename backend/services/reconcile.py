import logging
from datetime import datetime, timedelta, timezone

import httpx
from supabase import Client

from services.github import get_github_token
from services.github_sync import handle_issue_change, handle_pr_change, upsert_issue, upsert_pr

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

    token = get_github_token(db, workspace["owner_id"])
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
    is_new = not (
        db.table("github_issues")
        .select("id")
        .eq("workspace_id", workspace["id"])
        .eq("github_id", issue["id"])
        .execute()
        .data
    )
    saved = await upsert_issue(db, workspace["id"], issue)
    action = "opened" if is_new else "updated"
    await handle_issue_change(db, workspace, saved, action, gemini_key, is_new=is_new)


async def _upsert_pr(db: Client, workspace: dict, pr: dict, gemini_key: str | None):
    is_new = not (
        db.table("github_prs")
        .select("id")
        .eq("workspace_id", workspace["id"])
        .eq("github_id", pr["id"])
        .execute()
        .data
    )
    saved = await upsert_pr(db, workspace["id"], pr)
    action = "opened" if is_new else "updated"
    await handle_pr_change(db, workspace, saved, action, gemini_key, is_new=is_new)


