"""Creation and delivery of in-app notifications.

Notifications are addressed either to a profile id (`user_id`) or, when the
recipient has no account yet, to a bare `github_username`. The username-addressed
rows sit unclaimed until that person signs in for the first time, at which point
`claim_pending` binds them to the new profile. This is what makes it possible to
notify someone who was invited before they ever visited Waypoint.

Notification creation must never break the action that triggered it — a failed
insert here should not roll back a successful invite — so `notify` swallows and
logs errors rather than propagating them.
"""

import logging

from supabase import Client

logger = logging.getLogger(__name__)

# Known notification types. Kept as constants so routers don't pass raw strings
# and the frontend renderer has a fixed set to switch on.
TYPE_INVITE = "workspace_invite"
TYPE_INVITE_ACCEPTED = "workspace_invite_accepted"
TYPE_ADDED_TO_WORKSPACE = "added_to_workspace"


def notify(
    db: Client,
    *,
    type: str,
    payload: dict | None = None,
    user_id: str | None = None,
    github_username: str | None = None,
    workspace_id: str | None = None,
) -> dict | None:
    """Insert one notification addressed to a user_id or a github_username.

    Exactly one addressee is required. Returns the inserted row, or None if the
    insert failed (the caller's primary action is intentionally unaffected).
    """
    if not user_id and not github_username:
        raise ValueError("notify requires either user_id or github_username")

    row = {
        "type": type,
        "payload": payload or {},
        "user_id": user_id,
        "github_username": github_username.lower() if github_username else None,
        "workspace_id": workspace_id,
    }
    try:
        result = db.table("notifications").insert(row).execute()
        return result.data[0] if result.data else None
    except Exception:
        logger.exception("Failed to create %s notification", type)
        return None


def claim_pending(db: Client, user_id: str, github_username: str) -> int:
    """Bind username-addressed notifications to a profile on first sign-in.

    Runs on every OAuth round trip (including routine reconnects), so it must be
    idempotent: the `user_id is null` filter means already-claimed rows are
    skipped. Returns the number of rows claimed.
    """
    if not github_username:
        return 0
    try:
        result = (
            db.table("notifications")
            .update({"user_id": user_id})
            .eq("github_username", github_username.lower())
            .is_("user_id", None)
            .execute()
        )
        return len(result.data or [])
    except Exception:
        logger.exception("Failed to claim pending notifications for %s", github_username)
        return 0
