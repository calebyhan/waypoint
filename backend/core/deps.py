from fastapi import Depends, Header, HTTPException, status
from supabase import Client

from core.supabase import get_supabase


async def get_current_user(
    authorization: str = Header(...),
    db: Client = Depends(get_supabase),
) -> dict:
    """Extract and validate the Supabase JWT from the Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    token = authorization.removeprefix("Bearer ")
    try:
        user_response = db.auth.get_user(token)
        return user_response.user.model_dump()
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
