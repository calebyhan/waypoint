import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from core.deps import get_current_user
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


@router.post("/{workspace_id}/archive", status_code=status.HTTP_200_OK)
async def archive_workspace(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_owner(db, workspace_id, user["id"])
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
    _assert_owner(db, workspace_id, user["id"])
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
    _assert_owner(db, workspace_id, user["id"])
    db.table("workspaces").delete().eq("id", workspace_id).execute()


@router.get("/{workspace_id}/repos")
async def list_repos_for_connection(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """List GitHub repos the user can connect to this workspace."""
    _assert_membership(db, workspace_id, user["id"])
    provider_token = get_github_token(db, user["id"])
    if not provider_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No GitHub token found")
    repos = await gh_list_repos(provider_token)
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
    _assert_owner(db, workspace_id, user["id"])
    result = (
        db.table("workspaces")
        .update({"repo_owner": body.repo_owner, "repo_name": body.repo_name})
        .eq("id", workspace_id)
        .execute()
    )
    return result.data[0] if result.data else None


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


# --- Team Members (project team, not platform users) ---

VALID_ROLES = {"frontend", "backend", "fullstack", "devops", "design", "qa", "pm"}


class TeamMemberCreate(BaseModel):
    name: str
    role: str = "fullstack"
    weekly_capacity_hours: int = 40


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
    _assert_membership(db, workspace_id, user["id"])
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
    _assert_membership(db, workspace_id, user["id"])
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
    _assert_membership(db, workspace_id, user["id"])
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
    _assert_membership(db, workspace_id, user["id"])
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
    _assert_membership(db, workspace_id, user["id"])
    db.table("team_members").delete().eq("id", member_id).execute()


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


