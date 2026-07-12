from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from core.crypto import decrypt_or_plaintext, encrypt
from core.deps import get_current_user
from core.permissions import get_role
from core.supabase import get_supabase

router = APIRouter(prefix="/auth", tags=["auth"])

# Prefix used when returning a masked Gemini API key from GET /auth/me.
# update_me recognizes it so a re-submitted mask never overwrites the real key.
GEMINI_KEY_MASK_PREFIX = "••••"


class UpdateProfile(BaseModel):
    gemini_api_key: str | None = None


class AuthCallback(BaseModel):
    github_token: str | None = None


def _mask_key(plaintext: str) -> str:
    return GEMINI_KEY_MASK_PREFIX + plaintext[-4:] if len(plaintext) > 4 else GEMINI_KEY_MASK_PREFIX


def _profile_response(profile: dict) -> dict:
    """Shape a profiles row for API responses: never return the raw Gemini key."""
    data = {k: v for k, v in profile.items() if k not in {"gemini_api_key", "github_token"}}
    plaintext = decrypt_or_plaintext(profile.get("gemini_api_key"))
    data["has_gemini_key"] = bool(plaintext)
    data["gemini_api_key"] = _mask_key(plaintext) if plaintext else None
    return data


@router.get("/me")
async def get_me(
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Return the current user's profile. The Gemini API key is masked."""
    result = (
        db.table("profiles")
        .select("id, github_username, avatar_url, gemini_api_key, created_at")
        .eq("id", user["id"])
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return _profile_response(result.data)


@router.patch("/me")
async def update_me(
    body: UpdateProfile,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Update the current user's profile (e.g., Gemini API key).

    The Gemini key is encrypted at rest. A re-submitted masked value (from
    GET /auth/me) is ignored rather than overwriting the stored key; an empty
    string clears the key.
    """
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "gemini_api_key" in updates:
        key = updates["gemini_api_key"].strip()
        if key.startswith(GEMINI_KEY_MASK_PREFIX):
            # The frontend echoed back the masked placeholder — not a change.
            updates.pop("gemini_api_key")
        elif key == "":
            updates["gemini_api_key"] = None
        else:
            updates["gemini_api_key"] = encrypt(key)

    if updates:
        db.table("profiles").update(updates).eq("id", user["id"]).execute()

    result = db.table("profiles").select("*").eq("id", user["id"]).single().execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return _profile_response(result.data)


@router.post("/callback")
async def auth_callback(
    body: AuthCallback,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Called after Supabase OAuth login to ensure a profile row exists.

    Supabase only returns the GitHub provider token on the session at sign-in
    time, so the frontend forwards it here to be persisted for later API calls.
    """
    existing = db.table("profiles").select("id").eq("id", user["id"]).execute()
    if existing.data:
        if body.github_token:
            db.table("profiles").update({"github_token": encrypt(body.github_token)}).eq("id", user["id"]).execute()
        _resolve_pending_invites(db, user)
        return {"status": "existing", "profile_id": user["id"]}

    user_meta = user.get("user_metadata", {})
    db.table("profiles").insert({
        "id": user["id"],
        "github_username": user_meta.get("user_name", user_meta.get("preferred_username", "")),
        "avatar_url": user_meta.get("avatar_url"),
        "github_token": encrypt(body.github_token) if body.github_token else None,
    }).execute()
    _resolve_pending_invites(db, user)
    return {"status": "created", "profile_id": user["id"]}


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


def _resolve_pending_invites(db: Client, user: dict) -> None:
    """Auto-accept pending workspace invites addressed to this user's GitHub username.

    Invariants enforced here (this runs on *every* OAuth round trip, including
    routine "Reconnect GitHub" flows, so it must be safe to re-run):
    - An invite never changes the role of an existing workspace member. If the
      user is already a member of the invite's workspace (owner included), the
      invite is marked revoked and the membership row is left untouched.
    - Expired invites are never accepted; they're marked 'expired'.
    """
    user_meta = user.get("user_metadata", {})
    github_username = user_meta.get("user_name", user_meta.get("preferred_username", "")).lower()
    if not github_username:
        return

    pending = (
        db.table("workspace_invites")
        .select("*")
        .eq("github_username", github_username)
        .eq("status", "pending")
        .execute()
    )
    now = datetime.now(timezone.utc)
    for invite in pending.data:
        expires_at = _parse_timestamp(invite.get("expires_at"))
        if expires_at is not None and expires_at <= now:
            db.table("workspace_invites").update({"status": "expired"}).eq("id", invite["id"]).execute()
            continue

        if get_role(db, invite["workspace_id"], user["id"]) is not None:
            # Already a member: role changes must go through
            # PATCH /workspaces/{id}/members/{user_id}, which protects the owner.
            db.table("workspace_invites").update({"status": "revoked"}).eq("id", invite["id"]).execute()
            continue

        db.table("workspace_members").upsert(
            {
                "workspace_id": invite["workspace_id"],
                "user_id": user["id"],
                "role": invite["role"],
            },
            on_conflict="workspace_id,user_id",
        ).execute()
        db.table("workspace_invites").update({"status": "accepted"}).eq("id", invite["id"]).execute()
