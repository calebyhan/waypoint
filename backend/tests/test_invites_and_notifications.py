"""Invite delivery via tokenized links, and the notification feed behind it.

The case that drives most of this: someone can be invited before they have a
Waypoint account at all. There is no email address to reach them with, so the
invite URL is the delivery mechanism and the notification addressed to their bare
GitHub username is claimed later, on first sign-in.
"""

from tests.conftest import OTHER_USER_ID, USER_ID

INVITEE = "newcomer"


def _profile(fake_db, user_id: str, github_username: str):
    return fake_db.table("profiles").insert({
        "id": user_id,
        "github_username": github_username,
    }).execute().data[0]


def _create_invite(client, workspace, username=INVITEE, role="member"):
    res = client.post(
        f"/workspaces/{workspace['id']}/invites",
        json={"github_username": username, "role": role},
    )
    assert res.status_code == 201, res.text
    return res.json()


# --- Invite creation ---


def test_create_invite_returns_shareable_url(client, fake_db, workspace):
    _profile(fake_db, USER_ID, "pmuser")

    invite = _create_invite(client, workspace)

    assert invite["token"]
    assert invite["invite_url"].endswith(f"/invite/{invite['token']}")


def test_create_invite_tokens_are_unguessable_and_unique(client, fake_db, workspace):
    _profile(fake_db, USER_ID, "pmuser")

    first = _create_invite(client, workspace, username="alpha")
    second = _create_invite(client, workspace, username="beta")

    assert first["token"] != second["token"]
    # secrets.token_urlsafe(32) -> ~43 chars of base64url.
    assert len(first["token"]) >= 40


def test_create_invite_notifies_by_username_when_no_account_exists(client, fake_db, workspace):
    _profile(fake_db, USER_ID, "pmuser")

    _create_invite(client, workspace)

    notes = fake_db.table("notifications").select("*").execute().data
    assert len(notes) == 1
    assert notes[0]["type"] == "workspace_invite"
    assert notes[0]["github_username"] == INVITEE
    assert notes[0]["user_id"] is None, "nobody to address it to yet"
    assert notes[0]["payload"]["workspace_name"] == "Test Workspace"
    assert notes[0]["payload"]["invited_by"] == "pmuser"


def test_list_invites_exposes_url_for_recopying(client, fake_db, workspace):
    _profile(fake_db, USER_ID, "pmuser")
    created = _create_invite(client, workspace)

    res = client.get(f"/workspaces/{workspace['id']}/invites")

    assert res.status_code == 200
    assert res.json()[0]["invite_url"].endswith(f"/invite/{created['token']}")


# --- Public preview ---


def test_preview_invite_needs_no_auth_and_hides_internals(client, fake_db, workspace):
    _profile(fake_db, USER_ID, "pmuser")
    invite = _create_invite(client, workspace)

    res = client.get(f"/invites/{invite['token']}")

    assert res.status_code == 200
    body = res.json()
    assert body["workspace_name"] == "Test Workspace"
    assert body["invited_username"] == INVITEE
    assert body["invited_by"] == "pmuser"
    assert body["role"] == "member"
    assert body["is_expired"] is False
    # A leaked token must not expose workspace internals.
    assert "workspace_id" not in body
    assert "repo_owner" not in body
    assert "webhook_secret" not in body


def test_preview_unknown_token_is_404(client):
    assert client.get("/invites/does-not-exist").status_code == 404


def test_preview_reports_expiry(client, fake_db, workspace):
    _profile(fake_db, USER_ID, "pmuser")
    invite = _create_invite(client, workspace)
    fake_db.table("workspace_invites").update(
        {"expires_at": "2020-01-01T00:00:00+00:00"}
    ).eq("id", invite["id"]).execute()

    body = client.get(f"/invites/{invite['token']}").json()

    assert body["is_expired"] is True
    assert body["status"] == "expired"


# --- Accepting ---


def test_accept_binds_invite_to_the_named_github_user(client, fake_db, workspace, as_user):
    _profile(fake_db, USER_ID, "pmuser")
    invite = _create_invite(client, workspace)
    _profile(fake_db, OTHER_USER_ID, INVITEE)

    with as_user(OTHER_USER_ID, {"user_name": INVITEE}):
        res = client.post(f"/invites/{invite['token']}/accept")

    assert res.status_code == 200
    assert res.json()["status"] == "accepted"

    members = (
        fake_db.table("workspace_members")
        .select("*")
        .eq("workspace_id", workspace["id"])
        .eq("user_id", OTHER_USER_ID)
        .execute()
        .data
    )
    assert members[0]["role"] == "member"


def test_accept_rejects_a_forwarded_link(client, fake_db, workspace, as_user):
    """A leaked invite URL must be inert for anyone but the named user."""
    _profile(fake_db, USER_ID, "pmuser")
    invite = _create_invite(client, workspace)
    _profile(fake_db, OTHER_USER_ID, "eavesdropper")

    with as_user(OTHER_USER_ID, {"user_name": "eavesdropper"}):
        res = client.post(f"/invites/{invite['token']}/accept")

    assert res.status_code == 403
    assert "@newcomer" in res.json()["detail"]
    assert (
        fake_db.table("workspace_members")
        .select("*")
        .eq("user_id", OTHER_USER_ID)
        .execute()
        .data
        == []
    )


def test_accept_is_idempotent_after_login_time_resolution(client, fake_db, workspace, as_user):
    """/auth/callback often accepts the invite first; the landing page must not error."""
    _profile(fake_db, USER_ID, "pmuser")
    invite = _create_invite(client, workspace)
    _profile(fake_db, OTHER_USER_ID, INVITEE)

    with as_user(OTHER_USER_ID, {"user_name": INVITEE}):
        first = client.post(f"/invites/{invite['token']}/accept")
        second = client.post(f"/invites/{invite['token']}/accept")

    assert first.json()["status"] == "accepted"
    assert second.status_code == 200
    assert second.json()["status"] == "already_member"

    memberships = (
        fake_db.table("workspace_members")
        .select("*")
        .eq("workspace_id", workspace["id"])
        .eq("user_id", OTHER_USER_ID)
        .execute()
        .data
    )
    assert len(memberships) == 1, "accepting twice must not duplicate membership"


def test_accept_never_reroles_an_existing_member(client, fake_db, workspace, as_user):
    """An invite must not be a backdoor for escalating an existing member."""
    _profile(fake_db, USER_ID, "pmuser")
    fake_db.table("workspace_members").insert({
        "workspace_id": workspace["id"],
        "user_id": OTHER_USER_ID,
        "role": "member",
    }).execute()
    _profile(fake_db, OTHER_USER_ID, INVITEE)
    # Craft a pm invite directly (create_invite would 409 on an existing member).
    invite = fake_db.table("workspace_invites").insert({
        "workspace_id": workspace["id"],
        "github_username": INVITEE,
        "role": "pm",
        "invited_by": USER_ID,
        "status": "pending",
        "token": "crafted-token",
    }).execute().data[0]

    with as_user(OTHER_USER_ID, {"user_name": INVITEE}):
        res = client.post(f"/invites/{invite['token']}/accept")

    assert res.json()["status"] == "already_member"
    role = (
        fake_db.table("workspace_members")
        .select("role")
        .eq("workspace_id", workspace["id"])
        .eq("user_id", OTHER_USER_ID)
        .execute()
        .data[0]["role"]
    )
    assert role == "member", "invite must not have escalated them to pm"


def test_accept_rejects_expired_invite(client, fake_db, workspace, as_user):
    _profile(fake_db, USER_ID, "pmuser")
    invite = _create_invite(client, workspace)
    fake_db.table("workspace_invites").update(
        {"expires_at": "2020-01-01T00:00:00+00:00"}
    ).eq("id", invite["id"]).execute()
    _profile(fake_db, OTHER_USER_ID, INVITEE)

    with as_user(OTHER_USER_ID, {"user_name": INVITEE}):
        res = client.post(f"/invites/{invite['token']}/accept")

    assert res.status_code == 410
    assert "expired" in res.json()["detail"].lower()


def test_accept_notifies_the_inviting_pm(client, fake_db, workspace, as_user):
    _profile(fake_db, USER_ID, "pmuser")
    invite = _create_invite(client, workspace)
    _profile(fake_db, OTHER_USER_ID, INVITEE)

    with as_user(OTHER_USER_ID, {"user_name": INVITEE}):
        client.post(f"/invites/{invite['token']}/accept")

    pm_notes = (
        fake_db.table("notifications")
        .select("*")
        .eq("user_id", USER_ID)
        .execute()
        .data
    )
    assert [n["type"] for n in pm_notes] == ["workspace_invite_accepted"]
    assert pm_notes[0]["payload"]["github_username"] == INVITEE


# --- The pre-account case ---


def test_notification_sent_before_signup_is_claimed_on_first_login(
    client, fake_db, workspace, as_user
):
    """The whole point: invite someone who has no account, and have it reach them.

    At invite time there is no profile row, so the notification is addressed to a
    bare GitHub username. Their first OAuth round trip binds it to the new profile,
    so the bell is already populated the moment they land.
    """
    _profile(fake_db, USER_ID, "pmuser")
    _create_invite(client, workspace)

    # Nothing is addressed to them yet — they don't exist.
    unclaimed = fake_db.table("notifications").select("*").execute().data[0]
    assert unclaimed["user_id"] is None

    # They sign up for the first time.
    with as_user(OTHER_USER_ID, {"user_name": INVITEE}):
        assert client.post("/auth/callback", json={}).status_code == 200
        feed = client.get("/notifications").json()

    types = {n["type"] for n in feed}
    assert "workspace_invite" in types, "the pre-signup invite notification followed them in"
    assert "added_to_workspace" in types, "and they were told they now have access"


def test_claiming_is_idempotent_across_repeat_logins(client, fake_db, workspace, as_user):
    """/auth/callback runs on every reconnect, not just signup."""
    _profile(fake_db, USER_ID, "pmuser")
    _create_invite(client, workspace)

    with as_user(OTHER_USER_ID, {"user_name": INVITEE}):
        client.post("/auth/callback", json={})
        first = client.get("/notifications").json()
        client.post("/auth/callback", json={})
        second = client.get("/notifications").json()

    assert len(first) == len(second), "re-login must not duplicate notifications"


def test_username_matching_is_case_insensitive(client, fake_db, workspace, as_user):
    """GitHub handles are case-preserving but case-insensitive; a PM may type either."""
    _profile(fake_db, USER_ID, "pmuser")
    _create_invite(client, workspace, username="MixedCase")

    with as_user(OTHER_USER_ID, {"user_name": "mixedcase"}):
        client.post("/auth/callback", json={})
        feed = client.get("/notifications").json()

    assert any(n["type"] == "workspace_invite" for n in feed)


def test_unclaimed_notification_is_invisible_to_everyone(client, fake_db, workspace):
    """An unclaimed row must not leak into any user's feed before it is bound."""
    _profile(fake_db, USER_ID, "pmuser")
    _create_invite(client, workspace)

    assert client.get("/notifications").json() == []
    assert client.get("/notifications/unread-count").json()["count"] == 0


# --- Notification feed ---


def test_feed_only_returns_your_own_notifications(client, fake_db, workspace):
    fake_db.table("notifications").insert({
        "user_id": USER_ID, "type": "workspace_invite", "payload": {}, "github_username": None,
    }).execute()
    fake_db.table("notifications").insert({
        "user_id": OTHER_USER_ID, "type": "workspace_invite", "payload": {}, "github_username": None,
    }).execute()

    res = client.get("/notifications")

    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["user_id"] == USER_ID


def test_unread_count_and_mark_read(client, fake_db):
    note = fake_db.table("notifications").insert({
        "user_id": USER_ID, "type": "workspace_invite", "payload": {},
        "github_username": None, "read_at": None,
    }).execute().data[0]

    assert client.get("/notifications/unread-count").json()["count"] == 1

    res = client.post(f"/notifications/{note['id']}/read")
    assert res.status_code == 200
    assert res.json()["read_at"] is not None
    assert client.get("/notifications/unread-count").json()["count"] == 0


def test_cannot_mark_another_users_notification_read(client, fake_db):
    note = fake_db.table("notifications").insert({
        "user_id": OTHER_USER_ID, "type": "workspace_invite", "payload": {},
        "github_username": None, "read_at": None,
    }).execute().data[0]

    res = client.post(f"/notifications/{note['id']}/read")

    assert res.status_code == 404
    still_unread = fake_db.table("notifications").select("*").eq("id", note["id"]).execute().data[0]
    assert still_unread["read_at"] is None


def test_mark_all_read(client, fake_db):
    for _ in range(3):
        fake_db.table("notifications").insert({
            "user_id": USER_ID, "type": "workspace_invite", "payload": {},
            "github_username": None, "read_at": None,
        }).execute()

    assert client.post("/notifications/read-all").status_code == 204
    assert client.get("/notifications/unread-count").json()["count"] == 0


def test_unread_only_filter(client, fake_db):
    fake_db.table("notifications").insert({
        "user_id": USER_ID, "type": "a", "payload": {},
        "github_username": None, "read_at": None,
    }).execute()
    fake_db.table("notifications").insert({
        "user_id": USER_ID, "type": "b", "payload": {},
        "github_username": None, "read_at": "2024-01-01T00:00:00+00:00",
    }).execute()

    assert len(client.get("/notifications").json()) == 2
    unread = client.get("/notifications?unread_only=true").json()
    assert [n["type"] for n in unread] == ["a"]
