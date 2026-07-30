"""The in-app notification feed for the signed-in user."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from core.deps import get_current_user
from core.supabase import get_supabase

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    query = db.table("notifications").select("*").eq("user_id", user["id"])
    if unread_only:
        query = query.is_("read_at", None)
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data


@router.get("/unread-count")
async def unread_count(
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    result = (
        db.table("notifications")
        .select("id")
        .eq("user_id", user["id"])
        .is_("read_at", None)
        .execute()
    )
    return {"count": len(result.data or [])}


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    # Scoped by user_id as well as id so one user can never mark another's
    # notification read by guessing an id.
    result = (
        db.table("notifications")
        .update({"read_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", notification_id)
        .eq("user_id", user["id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return result.data[0]


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    (
        db.table("notifications")
        .update({"read_at": datetime.now(timezone.utc).isoformat()})
        .eq("user_id", user["id"])
        .is_("read_at", None)
        .execute()
    )
