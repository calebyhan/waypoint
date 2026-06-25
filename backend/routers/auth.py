from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from core.deps import get_current_user
from core.supabase import get_supabase

router = APIRouter(prefix="/auth", tags=["auth"])


class UpdateProfile(BaseModel):
    gemini_api_key: str | None = None


@router.get("/me")
async def get_me(
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Return the current user's profile."""
    result = db.table("profiles").select("*").eq("id", user["id"]).single().execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return result.data


@router.patch("/me")
async def update_me(
    body: UpdateProfile,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Update the current user's profile (e.g., Gemini API key)."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    result = db.table("profiles").update(updates).eq("id", user["id"]).execute()
    return result.data[0] if result.data else None


@router.post("/callback")
async def auth_callback(
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Called after Supabase OAuth login to ensure a profile row exists."""
    existing = db.table("profiles").select("id").eq("id", user["id"]).execute()
    if existing.data:
        return {"status": "existing", "profile_id": user["id"]}

    user_meta = user.get("user_metadata", {})
    db.table("profiles").insert({
        "id": user["id"],
        "github_username": user_meta.get("user_name", user_meta.get("preferred_username", "")),
        "avatar_url": user_meta.get("avatar_url"),
    }).execute()
    return {"status": "created", "profile_id": user["id"]}
