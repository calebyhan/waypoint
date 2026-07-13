from fastapi import HTTPException, status
from supabase import Client

ROLE_ORDER = {"member": 0, "pm": 1, "owner": 2}


def get_role(db: Client, workspace_id: str, user_id: str) -> str | None:
    result = (
        db.table("workspace_members")
        .select("role")
        .eq("workspace_id", workspace_id)
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0]["role"] if result.data else None


def assert_workspace_active(db: Client, workspace_id: str) -> dict:
    """Reject writes against non-active (archived/deleted) workspaces.

    docs/data-model.md: archived workspaces are read-only. Every endpoint that
    mutates workspace-scoped data calls this after its membership check, so the
    read-only guarantee lives in one place. Archive/restore/delete themselves
    are exempt (they manage the state transition itself).
    """
    result = db.table("workspaces").select("id, state").eq("id", workspace_id).single().execute()
    workspace = result.data
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    state = workspace.get("state")
    if state != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace is archived and read-only" if state == "archived" else f"Workspace is {state}",
        )
    return workspace


def assert_role(db: Client, workspace_id: str, user_id: str, minimum: str = "member") -> str:
    role = get_role(db, workspace_id, user_id)
    # An unknown role value (e.g. a future migration adding a role without
    # updating ROLE_ORDER) must degrade to 403, not a KeyError/500.
    if role is None or role not in ROLE_ORDER or minimum not in ROLE_ORDER or ROLE_ORDER[role] < ROLE_ORDER[minimum]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires {minimum} role or higher")
    return role
