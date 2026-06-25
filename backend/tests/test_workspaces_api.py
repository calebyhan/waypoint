from tests.conftest import USER_ID


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


def test_delete_workspace_soft_deletes(client, fake_db, workspace):
    res = client.delete(f"/workspaces/{workspace['id']}")

    assert res.status_code == 204
    updated = fake_db.table("workspaces").select("*").eq("id", workspace["id"]).single().execute().data
    assert updated["state"] == "deleted"


def test_delete_workspace_requires_ownership(client, fake_db, workspace):
    # Change the owner so the requesting user (USER_ID) is no longer the owner.
    fake_db.table("workspaces").update({"owner_id": "someone-else"}).eq("id", workspace["id"]).execute()

    res = client.delete(f"/workspaces/{workspace['id']}")

    assert res.status_code == 403
