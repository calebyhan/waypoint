import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from core.deps import get_current_user
from core.permissions import assert_role, assert_workspace_active, get_role
from core.supabase import get_supabase
from services.github import get_github_token, list_repos as gh_list_repos

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
        "role": "owner",
    }).execute()

    return workspace


@router.get("")
async def list_workspaces(
    state: str | None = None,
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

    query = db.table("workspaces").select("*").in_("id", workspace_ids)
    if state:
        query = query.eq("state", state)
    else:
        query = query.neq("state", "deleted")
    result = query.execute()
    workspaces = result.data

    ingested = (
        db.table("ingestions")
        .select("workspace_id")
        .in_("workspace_id", workspace_ids)
        .not_.is_("decomposition", "null")
        .execute()
    )
    ingested_ids = {row["workspace_id"] for row in ingested.data}

    for ws in workspaces:
        ws["has_ingestion"] = ws["id"] in ingested_ids

    return workspaces


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="member")
    result = db.table("workspaces").select("*").eq("id", workspace_id).single().execute()
    return result.data


@router.patch("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    body: UpdateWorkspace,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    result = db.table("workspaces").update(updates).eq("id", workspace_id).execute()
    return result.data[0] if result.data else None


@router.post("/{workspace_id}/archive", status_code=status.HTTP_200_OK)
async def archive_workspace(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    result = (
        db.table("workspaces")
        .update({"state": "archived"})
        .eq("id", workspace_id)
        .execute()
    )
    return result.data[0] if result.data else None


@router.post("/{workspace_id}/restore", status_code=status.HTTP_200_OK)
async def restore_workspace(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    result = (
        db.table("workspaces")
        .update({"state": "active"})
        .eq("id", workspace_id)
        .execute()
    )
    return result.data[0] if result.data else None


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="owner")
    db.table("workspaces").delete().eq("id", workspace_id).execute()


@router.get("/{workspace_id}/repos")
async def list_repos_for_connection(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """List GitHub repos the user can connect to this workspace."""
    assert_role(db, workspace_id, user["id"], minimum="member")
    provider_token = get_github_token(db, user["id"])
    if not provider_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub isn't connected. Reconnect your GitHub account to continue.",
        )
    try:
        repos = await gh_list_repos(provider_token)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your GitHub connection has expired. Reconnect your GitHub account to continue.",
            ) from e
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch repositories from GitHub. Please try again.",
        ) from e
    return repos


class ConnectRepo(BaseModel):
    repo_owner: str
    repo_name: str


@router.post("/{workspace_id}/connect-repo")
async def connect_repo(
    workspace_id: str,
    body: ConnectRepo,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Connect a GitHub repo to the workspace."""
    assert_role(db, workspace_id, user["id"], minimum="pm")
    assert_workspace_active(db, workspace_id)
    result = (
        db.table("workspaces")
        .update({"repo_owner": body.repo_owner, "repo_name": body.repo_name})
        .eq("id", workspace_id)
        .execute()
    )
    return result.data[0] if result.data else None


# --- Members & invites ---


@router.get("/{workspace_id}/members")
async def list_members(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="member")
    memberships = (
        db.table("workspace_members")
        .select("*")
        .eq("workspace_id", workspace_id)
        .execute()
        .data
    )
    profile_ids = [m["user_id"] for m in memberships]
    profiles = (
        db.table("profiles")
        .select("id, github_username, avatar_url")
        .in_("id", profile_ids)
        .execute()
        .data
        if profile_ids
        else []
    )
    profiles_by_id = {p["id"]: p for p in profiles}
    return [
        {
            "user_id": m["user_id"],
            "role": m["role"],
            "github_username": profiles_by_id.get(m["user_id"], {}).get("github_username"),
            "avatar_url": profiles_by_id.get(m["user_id"], {}).get("avatar_url"),
        }
        for m in memberships
    ]


class UpdateMemberRole(BaseModel):
    role: str


@router.patch("/{workspace_id}/members/{member_user_id}")
async def update_member_role(
    workspace_id: str,
    member_user_id: str,
    body: UpdateMemberRole,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    assert_workspace_active(db, workspace_id)
    if body.role not in {"pm", "member"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role must be 'pm' or 'member'")
    if get_role(db, workspace_id, member_user_id) == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot change the owner's role")
    result = (
        db.table("workspace_members")
        .update({"role": body.role})
        .eq("workspace_id", workspace_id)
        .eq("user_id", member_user_id)
        .execute()
    )
    return result.data[0] if result.data else None


@router.delete("/{workspace_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    workspace_id: str,
    member_user_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    assert_workspace_active(db, workspace_id)
    if get_role(db, workspace_id, member_user_id) == "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot remove the workspace owner")
    db.table("workspace_members").delete().eq("workspace_id", workspace_id).eq("user_id", member_user_id).execute()


class CreateInvite(BaseModel):
    github_username: str
    role: str = "member"


@router.post("/{workspace_id}/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    workspace_id: str,
    body: CreateInvite,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    assert_workspace_active(db, workspace_id)
    if body.role not in {"pm", "member"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role must be 'pm' or 'member'")
    result = db.table("workspace_invites").insert({
        "workspace_id": workspace_id,
        "github_username": body.github_username.strip().lower(),
        "role": body.role,
        "invited_by": user["id"],
        "status": "pending",
    }).execute()
    return result.data[0]


@router.get("/{workspace_id}/invites")
async def list_invites(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    result = (
        db.table("workspace_invites")
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("status", "pending")
        .order("created_at")
        .execute()
    )
    return result.data


@router.delete("/{workspace_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    workspace_id: str,
    invite_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    assert_workspace_active(db, workspace_id)
    db.table("workspace_invites").update({"status": "revoked"}).eq("id", invite_id).eq(
        "workspace_id", workspace_id
    ).execute()


# --- Team Members (project team, not platform users) ---

VALID_ROLES = {"frontend", "backend", "fullstack", "devops", "design", "qa", "pm"}


class TeamMemberCreate(BaseModel):
    name: str
    role: str = "fullstack"
    weekly_capacity_hours: int = 40
    user_id: str | None = None


class TeamMemberUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    weekly_capacity_hours: int | None = None


class TeamMemberBulkSync(BaseModel):
    members: list[TeamMemberCreate]


@router.get("/{workspace_id}/team")
async def list_team_members(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="member")
    result = (
        db.table("team_members")
        .select("*")
        .eq("workspace_id", workspace_id)
        .order("created_at")
        .execute()
    )
    return result.data


@router.post("/{workspace_id}/team", status_code=status.HTTP_201_CREATED)
async def create_team_member(
    workspace_id: str,
    body: TeamMemberCreate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    assert_workspace_active(db, workspace_id)
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role: {body.role}")
    result = db.table("team_members").insert({
        "workspace_id": workspace_id,
        "name": body.name,
        "role": body.role,
        "weekly_capacity_hours": body.weekly_capacity_hours,
    }).execute()
    return result.data[0]


@router.put("/{workspace_id}/team/sync")
async def sync_team_members(
    workspace_id: str,
    body: TeamMemberBulkSync,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Replace all team members for a workspace (used by ingest wizard)."""
    assert_role(db, workspace_id, user["id"], minimum="pm")
    assert_workspace_active(db, workspace_id)
    for m in body.members:
        if m.role not in VALID_ROLES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role: {m.role}")

    db.table("team_members").delete().eq("workspace_id", workspace_id).execute()
    if body.members:
        rows = [
            {
                "workspace_id": workspace_id,
                "name": m.name,
                "role": m.role,
                "weekly_capacity_hours": m.weekly_capacity_hours,
                "user_id": m.user_id,
            }
            for m in body.members
        ]
        db.table("team_members").insert(rows).execute()

    return {"status": "synced", "count": len(body.members)}


@router.patch("/{workspace_id}/team/{member_id}")
async def update_team_member(
    workspace_id: str,
    member_id: str,
    body: TeamMemberUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    assert_workspace_active(db, workspace_id)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    if "role" in updates and updates["role"] not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role: {updates['role']}")
    result = db.table("team_members").update(updates).eq("id", member_id).execute()
    return result.data[0] if result.data else None


@router.delete("/{workspace_id}/team/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team_member(
    workspace_id: str,
    member_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    assert_role(db, workspace_id, user["id"], minimum="pm")
    assert_workspace_active(db, workspace_id)
    db.table("team_members").delete().eq("id", member_id).execute()


class LinkTeamMember(BaseModel):
    user_id: str | None = None


@router.post("/{workspace_id}/team/{member_id}/link")
async def link_team_member(
    workspace_id: str,
    member_id: str,
    body: LinkTeamMember,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Link (or unlink, if user_id is null) a scheduling-roster row to a real workspace member's account."""
    assert_role(db, workspace_id, user["id"], minimum="pm")
    assert_workspace_active(db, workspace_id)
    if body.user_id is not None and get_role(db, workspace_id, body.user_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is not a member of this workspace")
    result = (
        db.table("team_members")
        .update({"user_id": body.user_id})
        .eq("id", member_id)
        .eq("workspace_id", workspace_id)
        .execute()
    )
    return result.data[0] if result.data else None


