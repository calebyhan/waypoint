import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from postgrest.exceptions import APIError
from supabase import Client

from core.crypto import decrypt_or_plaintext
from core.supabase import get_supabase
from services.github_sync import handle_issue_change, handle_pr_change, upsert_issue, upsert_pr

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
    stored = result.data.get("gemini_api_key") if result.data else None
    # Keys are encrypted at rest; pre-encryption rows are legacy plaintext.
    return decrypt_or_plaintext(stored)


def _record_delivery(db: Client, delivery_id: str) -> bool:
    """Record a webhook delivery ID. Returns False if it was already processed.

    GitHub sends a unique X-GitHub-Delivery UUID per delivery; the unique
    constraint on github_webhook_deliveries.delivery_id makes replayed
    (captured/re-sent) payloads detectable even though their HMAC signature
    is still valid.
    """
    try:
        db.table("github_webhook_deliveries").insert({"delivery_id": delivery_id}).execute()
    except APIError as e:
        if getattr(e, "code", None) == "23505":
            return False
        raise
    return True


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
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
        logger.warning(
            "Webhook signature verification failed for workspace=%s repo=%s/%s delivery=%s",
            workspace["id"], owner, name, x_github_delivery,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    if x_github_delivery and not _record_delivery(db, x_github_delivery):
        logger.info("Duplicate webhook delivery %s ignored", x_github_delivery)
        return {"status": "duplicate"}

    gemini_key = _get_gemini_key(db, workspace["owner_id"])

    if x_github_event == "issues":
        await _handle_issue_event(db, workspace, payload, gemini_key)
    elif x_github_event == "pull_request":
        await _handle_pr_event(db, workspace, payload, gemini_key)

    return {"status": "ok"}


async def _handle_issue_event(db: Client, workspace: dict, payload: dict, gemini_key: str | None):
    action = payload.get("action")
    issue = payload.get("issue", {})

    is_new = not (
        db.table("github_issues")
        .select("id")
        .eq("workspace_id", workspace["id"])
        .eq("github_id", issue["id"])
        .execute()
        .data
    )
    saved_issue = await upsert_issue(db, workspace["id"], issue)
    await handle_issue_change(db, workspace, saved_issue, action, gemini_key, is_new=is_new)


async def _handle_pr_event(db: Client, workspace: dict, payload: dict, gemini_key: str | None):
    action = payload.get("action")
    pr = payload.get("pull_request", {})

    is_new = not (
        db.table("github_prs")
        .select("id")
        .eq("workspace_id", workspace["id"])
        .eq("github_id", pr["id"])
        .execute()
        .data
    )
    saved_pr = await upsert_pr(db, workspace["id"], pr)
    await handle_pr_change(db, workspace, saved_pr, action, gemini_key, is_new=is_new)
