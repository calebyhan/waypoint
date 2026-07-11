from unittest.mock import AsyncMock

import httpx

from tests.conftest import OTHER_USER_ID, USER_ID


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.github.com/user/repos")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


def test_create_workspace_adds_creator_as_member(client, fake_db):
    res = client.post("/workspaces", json={"name": "My Project"})

    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "My Project"
    assert body["owner_id"] == USER_ID
    assert body["webhook_secret"]

    members = fake_db.table("workspace_members").select("*").eq("workspace_id", body["id"]).execute().data
    assert len(members) == 1
    assert members[0]["user_id"] == USER_ID
    assert members[0]["role"] == "owner"


def test_list_workspaces_excludes_deleted(client, fake_db, workspace):
    other = fake_db.table("workspaces").insert({
        "name": "Deleted one", "owner_id": USER_ID, "state": "deleted",
    }).execute().data[0]
    fake_db.table("workspace_members").insert({"workspace_id": other["id"], "user_id": USER_ID}).execute()

    res = client.get("/workspaces")

    assert res.status_code == 200
    names = [w["name"] for w in res.json()]
    assert "Test Workspace" in names
    assert "Deleted one" not in names


def test_list_workspaces_empty_for_non_member(client):
    res = client.get("/workspaces")
    assert res.status_code == 200
    assert res.json() == []


def test_get_workspace_requires_membership(client, fake_db):
    not_my_workspace = fake_db.table("workspaces").insert({
        "name": "Someone else's", "owner_id": "other-user", "state": "active",
    }).execute().data[0]

    res = client.get(f"/workspaces/{not_my_workspace['id']}")

    assert res.status_code == 403


def test_delete_workspace_permanently_removes_it(client, fake_db, workspace):
    res = client.delete(f"/workspaces/{workspace['id']}")

    assert res.status_code == 204
    remaining = fake_db.table("workspaces").select("*").eq("id", workspace["id"]).execute().data
    assert remaining == []


def test_delete_workspace_requires_ownership(client, fake_db, workspace):
    # Demote the requesting user's membership role so they're no longer the owner.
    fake_db.table("workspace_members").update({"role": "pm"}).eq("workspace_id", workspace["id"]).eq(
        "user_id", USER_ID
    ).execute()

    res = client.delete(f"/workspaces/{workspace['id']}")

    assert res.status_code == 403


def _add_member(fake_db, workspace_id, user_id, role):
    fake_db.table("workspace_members").insert({
        "workspace_id": workspace_id,
        "user_id": user_id,
        "role": role,
    }).execute()


def test_invite_creation_requires_pm_or_owner(client, fake_db, workspace, as_user):
    _add_member(fake_db, workspace["id"], OTHER_USER_ID, "member")

    with as_user(OTHER_USER_ID):
        res = client.post(f"/workspaces/{workspace['id']}/invites", json={"github_username": "octocat"})
    assert res.status_code == 403

    res = client.post(f"/workspaces/{workspace['id']}/invites", json={"github_username": "octocat", "role": "pm"})
    assert res.status_code == 201
    assert res.json()["github_username"] == "octocat"
    assert res.json()["role"] == "pm"


def test_invite_resolves_on_auth_callback(client, fake_db, workspace, as_user):
    client.post(f"/workspaces/{workspace['id']}/invites", json={"github_username": "Octocat", "role": "pm"})

    with as_user(OTHER_USER_ID, user_metadata={"user_name": "octocat"}):
        res = client.post("/auth/callback", json={})
    assert res.status_code == 200

    members = fake_db.table("workspace_members").select("*").eq("workspace_id", workspace["id"]).eq(
        "user_id", OTHER_USER_ID
    ).execute().data
    assert len(members) == 1
    assert members[0]["role"] == "pm"

    invites = fake_db.table("workspace_invites").select("*").eq("workspace_id", workspace["id"]).execute().data
    assert invites[0]["status"] == "accepted"


def test_update_member_role_cannot_touch_owner(client, fake_db, workspace):
    res = client.patch(f"/workspaces/{workspace['id']}/members/{USER_ID}", json={"role": "member"})
    assert res.status_code == 403


def test_update_member_role_rejects_promotion_to_owner(client, fake_db, workspace):
    _add_member(fake_db, workspace["id"], OTHER_USER_ID, "member")
    res = client.patch(f"/workspaces/{workspace['id']}/members/{OTHER_USER_ID}", json={"role": "owner"})
    assert res.status_code == 400


def test_remove_member_cannot_remove_owner(client, fake_db, workspace):
    res = client.delete(f"/workspaces/{workspace['id']}/members/{USER_ID}")
    assert res.status_code == 403


def test_member_cannot_manage_team_or_invite(client, fake_db, workspace, as_user):
    _add_member(fake_db, workspace["id"], OTHER_USER_ID, "member")

    with as_user(OTHER_USER_ID):
        assert client.post(f"/workspaces/{workspace['id']}/team", json={"name": "Alice"}).status_code == 403
        assert client.post(f"/workspaces/{workspace['id']}/invites", json={"github_username": "x"}).status_code == 403
        assert client.patch(
            f"/workspaces/{workspace['id']}/members/{USER_ID}", json={"role": "member"}
        ).status_code == 403


def test_pm_can_archive_but_not_delete(client, fake_db, workspace, as_user):
    _add_member(fake_db, workspace["id"], OTHER_USER_ID, "pm")

    with as_user(OTHER_USER_ID):
        assert client.post(f"/workspaces/{workspace['id']}/archive").status_code == 200
        assert client.delete(f"/workspaces/{workspace['id']}").status_code == 403


def test_link_team_member_requires_workspace_membership(client, fake_db, workspace):
    member = client.post(f"/workspaces/{workspace['id']}/team", json={"name": "Alice"}).json()

    res = client.post(f"/workspaces/{workspace['id']}/team/{member['id']}/link", json={"user_id": "not-a-member"})
    assert res.status_code == 400

    res = client.post(f"/workspaces/{workspace['id']}/team/{member['id']}/link", json={"user_id": USER_ID})
    assert res.status_code == 200
    assert res.json()["user_id"] == USER_ID


def test_list_repos_without_github_token_returns_400(client, fake_db, workspace, monkeypatch):
    monkeypatch.setattr("routers.workspaces.get_github_token", lambda db, user_id: None)

    res = client.get(f"/workspaces/{workspace['id']}/repos")

    assert res.status_code == 400
    assert "reconnect" in res.json()["detail"].lower()


def test_list_repos_expired_token_returns_401(client, fake_db, workspace, monkeypatch):
    monkeypatch.setattr("routers.workspaces.get_github_token", lambda db, user_id: "stale-token")
    monkeypatch.setattr(
        "routers.workspaces.gh_list_repos",
        AsyncMock(side_effect=_http_status_error(401)),
    )

    res = client.get(f"/workspaces/{workspace['id']}/repos")

    assert res.status_code == 401
    assert "reconnect" in res.json()["detail"].lower()


def test_list_repos_github_outage_returns_502(client, fake_db, workspace, monkeypatch):
    monkeypatch.setattr("routers.workspaces.get_github_token", lambda db, user_id: "tok")
    monkeypatch.setattr(
        "routers.workspaces.gh_list_repos",
        AsyncMock(side_effect=_http_status_error(500)),
    )

    res = client.get(f"/workspaces/{workspace['id']}/repos")

    assert res.status_code == 502


def test_list_repos_success(client, fake_db, workspace, monkeypatch):
    monkeypatch.setattr("routers.workspaces.get_github_token", lambda db, user_id: "tok")
    monkeypatch.setattr(
        "routers.workspaces.gh_list_repos",
        AsyncMock(return_value=[{"full_name": "acme/widgets", "owner": "acme", "name": "widgets"}]),
    )

    res = client.get(f"/workspaces/{workspace['id']}/repos")

    assert res.status_code == 200
    assert res.json() == [{"full_name": "acme/widgets", "owner": "acme", "name": "widgets"}]
