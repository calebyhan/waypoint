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


def assert_role(db: Client, workspace_id: str, user_id: str, minimum: str = "member") -> str:
    role = get_role(db, workspace_id, user_id)
    if role is None or ROLE_ORDER[role] < ROLE_ORDER[minimum]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires {minimum} role or higher")
    return role
