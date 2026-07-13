"""Archived workspaces are read-only and hidden from the default list
(docs/data-model.md). These tests cover the enforcement added in
core.permissions.assert_workspace_active and the list filtering."""

import pytest

from tests.conftest import USER_ID


@pytest.fixture
def archived_workspace(fake_db, workspace):
    fake_db.table("workspaces").update({"state": "archived"}).eq("id", workspace["id"]).execute()
    return workspace


def _seed_extra_workspace(fake_db, state):
    ws = fake_db.table("workspaces").insert({
        "name": f"{state} ws", "owner_id": USER_ID, "state": state, "webhook_secret": "s2",
    }).execute().data[0]
    fake_db.table("workspace_members").insert({
        "workspace_id": ws["id"], "user_id": USER_ID, "role": "owner",
    }).execute()
    return ws


# --- Default-list hiding -------------------------------------------------------


def test_default_list_excludes_archived_workspaces(client, fake_db, workspace):
    archived = _seed_extra_workspace(fake_db, "archived")

    res = client.get("/workspaces")

    ids = [w["id"] for w in res.json()]
    assert workspace["id"] in ids
    assert archived["id"] not in ids


def test_include_archived_true_returns_archived_workspaces(client, fake_db, workspace):
    archived = _seed_extra_workspace(fake_db, "archived")
    deleted = _seed_extra_workspace(fake_db, "deleted")

    res = client.get("/workspaces?include_archived=true")

    ids = [w["id"] for w in res.json()]
    assert workspace["id"] in ids
    assert archived["id"] in ids
    assert deleted["id"] not in ids  # deleted stays hidden either way


def test_explicit_state_filter_still_works(client, fake_db, workspace):
    archived = _seed_extra_workspace(fake_db, "archived")

    res = client.get("/workspaces?state=archived")

    ids = [w["id"] for w in res.json()]
    assert ids == [archived["id"]]


# --- Read-only enforcement ------------------------------------------------------


def test_archived_workspace_is_still_readable(client, fake_db, archived_workspace):
    assert client.get(f"/workspaces/{archived_workspace['id']}").status_code == 200
    assert client.get(f"/workspaces/{archived_workspace['id']}/dashboard").status_code == 200
    assert client.get(f"/workspaces/{archived_workspace['id']}/plan").status_code == 200


def test_task_status_patch_rejected_on_archived_workspace(client, fake_db, archived_workspace):
    task = fake_db.table("tasks").insert({
        "workspace_id": archived_workspace["id"], "title": "T", "status": "open", "priority": "p1",
    }).execute().data[0]

    res = client.patch(
        f"/workspaces/{archived_workspace['id']}/tasks/{task['id']}/status", json={"status": "done"}
    )

    assert res.status_code == 403
    assert "archived" in res.json()["detail"]
    unchanged = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert unchanged["status"] == "open"


def test_task_edit_rejected_on_archived_workspace(client, fake_db, archived_workspace):
    task = fake_db.table("tasks").insert({
        "workspace_id": archived_workspace["id"], "title": "T", "status": "open", "priority": "p1",
    }).execute().data[0]

    res = client.patch(
        f"/workspaces/{archived_workspace['id']}/tasks/{task['id']}", json={"title": "New title"}
    )

    assert res.status_code == 403


def test_task_create_rejected_on_archived_workspace(client, fake_db, archived_workspace):
    res = client.post(
        f"/workspaces/{archived_workspace['id']}/tasks",
        json={"epic_id": "e-1", "title": "New task"},
    )

    assert res.status_code == 403


def test_ingest_rejected_on_archived_workspace(client, fake_db, archived_workspace):
    res = client.post(f"/workspaces/{archived_workspace['id']}/ingest", json={"content": "PRD"})

    assert res.status_code == 403
    assert "archived" in res.json()["detail"]


def test_reingest_rejected_on_archived_workspace(client, fake_db, archived_workspace):
    res = client.post(f"/workspaces/{archived_workspace['id']}/reingest", json={"content": "PRD"})

    assert res.status_code == 403


def test_plan_approve_rejected_on_archived_workspace(client, fake_db, archived_workspace):
    res = client.post(f"/workspaces/{archived_workspace['id']}/plan/approve")

    assert res.status_code == 403


def test_invite_creation_rejected_on_archived_workspace(client, fake_db, archived_workspace):
    res = client.post(
        f"/workspaces/{archived_workspace['id']}/invites",
        json={"github_username": "bob", "role": "member"},
    )

    assert res.status_code == 403


def test_member_role_change_rejected_on_archived_workspace(client, fake_db, archived_workspace):
    res = client.patch(
        f"/workspaces/{archived_workspace['id']}/members/some-user",
        json={"role": "pm"},
    )

    assert res.status_code == 403


def test_reschedule_rejected_on_archived_workspace(client, fake_db, archived_workspace):
    fake_db.table("tasks").insert({
        "workspace_id": archived_workspace["id"], "title": "T", "status": "open", "priority": "p1",
    }).execute()

    res = client.post(f"/workspaces/{archived_workspace['id']}/reschedule", json={})

    assert res.status_code == 403


def test_team_sync_rejected_on_archived_workspace(client, fake_db, archived_workspace):
    res = client.put(
        f"/workspaces/{archived_workspace['id']}/team/sync", json={"members": []}
    )

    assert res.status_code == 403


def test_restore_then_mutations_work_again(client, fake_db, archived_workspace):
    task = fake_db.table("tasks").insert({
        "workspace_id": archived_workspace["id"], "title": "T", "status": "open", "priority": "p1",
    }).execute().data[0]

    restore = client.post(f"/workspaces/{archived_workspace['id']}/restore")
    assert restore.status_code == 200

    res = client.patch(
        f"/workspaces/{archived_workspace['id']}/tasks/{task['id']}/status", json={"status": "done"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "done"
