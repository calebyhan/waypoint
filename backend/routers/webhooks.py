import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from supabase import Client

from core.supabase import get_supabase
from services.matching import match_issue_to_task, match_pr_to_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _get_workspace_for_repo(db: Client, owner: str, name: str) -> dict | None:
    result = (
        db.table("workspaces")
        .select("*")
        .eq("repo_owner", owner)
        .eq("repo_name", name)
        .eq("state", "active")
        .execute()
    )
    return result.data[0] if result.data else None


def _get_gemini_key(db: Client, owner_id: str) -> str | None:
    result = db.table("profiles").select("gemini_api_key").eq("id", owner_id).single().execute()
    return result.data.get("gemini_api_key") if result.data else None


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
):
    db = get_supabase()
    raw_body = await request.body()
    payload = await request.json()

    repo = payload.get("repository", {})
    owner = repo.get("owner", {}).get("login")
    name = repo.get("name")

    if not owner or not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing repository info")

    workspace = _get_workspace_for_repo(db, owner, name)
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No workspace connected to this repo")

    if not _verify_signature(raw_body, x_hub_signature_256, workspace["webhook_secret"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    gemini_key = _get_gemini_key(db, workspace["owner_id"])

    if x_github_event == "issues":
        await _handle_issue_event(db, workspace, payload, gemini_key)
    elif x_github_event == "pull_request":
        await _handle_pr_event(db, workspace, payload, gemini_key)

    return {"status": "ok"}


async def _handle_issue_event(db: Client, workspace: dict, payload: dict, gemini_key: str | None):
    action = payload.get("action")
    issue = payload.get("issue", {})

    issue_row = {
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
        result = db.table("github_issues").update(issue_row).eq("id", existing.data[0]["id"]).execute()
        saved_issue = result.data[0]
    else:
        result = db.table("github_issues").insert(issue_row).execute()
        saved_issue = result.data[0]

    if action == "opened":
        await match_issue_to_task(db, workspace["id"], saved_issue, gemini_key)
    elif action == "closed" and saved_issue.get("linked_task_id"):
        _maybe_mark_done(db, saved_issue["linked_task_id"])


async def _handle_pr_event(db: Client, workspace: dict, payload: dict, gemini_key: str | None):
    action = payload.get("action")
    pr = payload.get("pull_request", {})

    pr_row = {
        "workspace_id": workspace["id"],
        "github_id": pr["id"],
        "number": pr["number"],
        "title": pr["title"],
        "state": pr["state"],
        "merged": pr.get("merged", False),
    }

    existing = (
        db.table("github_prs")
        .select("*")
        .eq("workspace_id", workspace["id"])
        .eq("github_id", pr["id"])
        .execute()
    )

    if existing.data:
        result = db.table("github_prs").update(pr_row).eq("id", existing.data[0]["id"]).execute()
        saved_pr = result.data[0]
    else:
        result = db.table("github_prs").insert(pr_row).execute()
        saved_pr = result.data[0]

    if action == "opened":
        proposal = await match_pr_to_task(db, workspace["id"], saved_pr, gemini_key)
        if proposal and proposal.get("task_id"):
            db.table("tasks").update({"status": "in_review"}).eq("id", proposal["task_id"]).execute()
    elif action == "closed" and pr.get("merged") and saved_pr.get("linked_task_id"):
        _maybe_mark_done(db, saved_pr["linked_task_id"])


def _maybe_mark_done(db: Client, task_id: str):
    """Mark task done only if both issue-closed and PR-merged signals are present."""
    issues = db.table("github_issues").select("state").eq("linked_task_id", task_id).execute()
    prs = db.table("github_prs").select("merged").eq("linked_task_id", task_id).execute()

    issue_closed = all(i["state"] == "closed" for i in issues.data) if issues.data else False
    pr_merged = any(p["merged"] for p in prs.data) if prs.data else False

    if issue_closed and pr_merged:
        db.table("tasks").update({"status": "done"}).eq("id", task_id).execute()
