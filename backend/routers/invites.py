"""Token-addressed invite endpoints backing the /invite/<token> landing page.

These live outside /workspaces/{id} because the recipient is by definition not
yet a member of that workspace — and may not even have an account. Possession of
the unguessable token is what authorizes the *preview*; actually joining still
requires signing in as the GitHub user the invite names.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from core.deps import get_current_user
from core.permissions import get_role
from core.supabase import get_supabase
from services import notifications

router = APIRouter(prefix="/invites", tags=["invites"])


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_invite(db: Client, token: str) -> dict:
    result = db.table("workspace_invites").select("*").eq("token", token).execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    return result.data[0]


def _caller_github_username(db: Client, user: dict) -> str:
    """Resolve the signed-in user's GitHub handle, preferring the stored profile.

    The profile row is written at /auth/callback from the same OAuth metadata, so
    it is the more stable source; user_metadata is the fallback for a session
    whose profile row has not been created yet.
    """
    profile = db.table("profiles").select("github_username").eq("id", user["id"]).execute()
    if profile.data and profile.data[0].get("github_username"):
        return profile.data[0]["github_username"].lower()
    meta = user.get("user_metadata", {})
    return meta.get("user_name", meta.get("preferred_username", "")).lower()


@router.get("/{token}")
async def preview_invite(token: str, db: Client = Depends(get_supabase)):
    """Unauthenticated preview so a signed-out recipient sees what they're joining.

    Deliberately minimal: enough to decide whether to sign in, and nothing that
    would make a leaked token useful as a data-exfiltration primitive. No member
    list, no repo, no workspace id.
    """
    invite = _load_invite(db, token)
    workspace = (
        db.table("workspaces").select("name").eq("id", invite["workspace_id"]).execute()
    )
    inviter = (
        db.table("profiles").select("github_username").eq("id", invite["invited_by"]).execute()
    )

    expires_at = _parse_timestamp(invite.get("expires_at"))
    is_expired = expires_at is not None and expires_at <= datetime.now(timezone.utc)

    return {
        "workspace_name": workspace.data[0]["name"] if workspace.data else None,
        "invited_username": invite["github_username"],
        "invited_by": inviter.data[0]["github_username"] if inviter.data else None,
        "role": invite["role"],
        "status": "expired" if is_expired and invite["status"] == "pending" else invite["status"],
        "is_expired": is_expired,
    }


@router.post("/{token}/accept")
async def accept_invite(
    token: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Join the workspace this invite names, as the GitHub user it is bound to.

    Idempotent by design. /auth/callback already auto-resolves pending invites by
    username on every login, so by the time the landing page calls this the
    membership frequently exists already — that is a success, not a conflict.
    """
    invite = _load_invite(db, token)
    caller = _caller_github_username(db, user)

    # Username binding: a forwarded or leaked link is inert for anyone else.
    if caller != invite["github_username"].lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This invite is for @{invite['github_username']}. "
                   f"You are signed in as @{caller or 'unknown'}.",
        )

    existing_role = get_role(db, invite["workspace_id"], user["id"])
    if existing_role is not None:
        # Already a member — either the login-time resolve beat us here, or they
        # were added directly. Never re-role an existing member from an invite.
        if invite["status"] == "pending":
            db.table("workspace_invites").update({
                "status": "accepted",
                "accepted_by": user["id"],
            }).eq("id", invite["id"]).execute()
        return {"status": "already_member", "workspace_id": invite["workspace_id"]}

    if invite["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"This invite has already been {invite['status']}.",
        )

    expires_at = _parse_timestamp(invite.get("expires_at"))
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        db.table("workspace_invites").update({"status": "expired"}).eq("id", invite["id"]).execute()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invite has expired. Ask for a new one.",
        )

    db.table("workspace_members").upsert(
        {
            "workspace_id": invite["workspace_id"],
            "user_id": user["id"],
            "role": invite["role"],
        },
        on_conflict="workspace_id,user_id",
    ).execute()
    db.table("workspace_invites").update({
        "status": "accepted",
        "accepted_by": user["id"],
    }).eq("id", invite["id"]).execute()

    # Close the loop for the PM who sent it.
    workspace = db.table("workspaces").select("name").eq("id", invite["workspace_id"]).execute()
    notifications.notify(
        db,
        type=notifications.TYPE_INVITE_ACCEPTED,
        user_id=invite["invited_by"],
        workspace_id=invite["workspace_id"],
        payload={
            "github_username": caller,
            "role": invite["role"],
            "workspace_name": workspace.data[0]["name"] if workspace.data else None,
        },
    )

    return {"status": "accepted", "workspace_id": invite["workspace_id"]}
