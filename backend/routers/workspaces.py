import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from core.deps import get_current_user
from core.supabase import get_supabase

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class CreateWorkspace(BaseModel):
    name: str


class UpdateWorkspace(BaseModel):
    name: str | None = None
    state: str | None = None
    repo_owner: str | None = None
    repo_name: str | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: CreateWorkspace,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    webhook_secret = secrets.token_hex(32)
    result = db.table("workspaces").insert({
        "name": body.name,
        "owner_id": user["id"],
        "webhook_secret": webhook_secret,
    }).execute()
    workspace = result.data[0]

    db.table("workspace_members").insert({
        "workspace_id": workspace["id"],
        "user_id": user["id"],
    }).execute()

    return workspace


@router.get("")
async def list_workspaces(
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    memberships = (
        db.table("workspace_members")
        .select("workspace_id")
        .eq("user_id", user["id"])
        .execute()
    )
    workspace_ids = [m["workspace_id"] for m in memberships.data]
    if not workspace_ids:
        return []

    result = (
        db.table("workspaces")
        .select("*")
        .in_("id", workspace_ids)
        .neq("state", "deleted")
        .execute()
    )
    return result.data


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    result = db.table("workspaces").select("*").eq("id", workspace_id).single().execute()
    return result.data


@router.patch("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    body: UpdateWorkspace,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_owner(db, workspace_id, user["id"])
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    result = db.table("workspaces").update(updates).eq("id", workspace_id).execute()
    return result.data[0] if result.data else None


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_owner(db, workspace_id, user["id"])
    db.table("workspaces").update({"state": "deleted"}).eq("id", workspace_id).execute()


class AddMember(BaseModel):
    user_id: str


@router.post("/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    workspace_id: str,
    body: AddMember,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_owner(db, workspace_id, user["id"])
    db.table("workspace_members").insert({
        "workspace_id": workspace_id,
        "user_id": body.user_id,
    }).execute()
    return {"status": "added"}


def _assert_membership(db: Client, workspace_id: str, user_id: str):
    result = (
        db.table("workspace_members")
        .select("workspace_id")
        .eq("workspace_id", workspace_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")


def _assert_owner(db: Client, workspace_id: str, user_id: str):
    result = (
        db.table("workspaces")
        .select("owner_id")
        .eq("id", workspace_id)
        .single()
        .execute()
    )
    if not result.data or result.data["owner_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the workspace owner")
