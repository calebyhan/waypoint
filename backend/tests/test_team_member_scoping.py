"""Regression tests: team_members writes must be scoped to the path workspace.

update_team_member and delete_team_member previously filtered only on the row id,
so a PM of workspace A could mutate a roster row belonging to workspace B just by
knowing its id — the membership check passed (they really are a PM of A) while
the write landed on someone else's data.
"""

def _other_workspace_with_member(fake_db):
    """A workspace USER_ID has no membership in, holding one roster row."""
    other_ws = fake_db.table("workspaces").insert({
        "name": "Someone else's workspace",
        "owner_id": "99999999-9999-9999-9999-999999999999",
        "state": "active",
    }).execute().data[0]
    victim = fake_db.table("team_members").insert({
        "workspace_id": other_ws["id"],
        "name": "Victim",
        "role": "backend",
        "weekly_capacity_hours": 40,
    }).execute().data[0]
    return other_ws, victim


def test_update_team_member_cannot_reach_another_workspace(client, fake_db, workspace):
    _, victim = _other_workspace_with_member(fake_db)

    # USER_ID is owner of `workspace`, so the permission check passes — the
    # question is whether the write is confined to that workspace.
    res = client.patch(
        f"/workspaces/{workspace['id']}/team/{victim['id']}",
        json={"name": "Pwned"},
    )

    assert res.status_code == 200
    assert res.json() is None, "no row in this workspace matched, so nothing should update"

    unchanged = fake_db.table("team_members").select("*").eq("id", victim["id"]).execute().data[0]
    assert unchanged["name"] == "Victim"


def test_delete_team_member_cannot_reach_another_workspace(client, fake_db, workspace):
    _, victim = _other_workspace_with_member(fake_db)

    res = client.delete(f"/workspaces/{workspace['id']}/team/{victim['id']}")

    assert res.status_code == 204
    survivors = fake_db.table("team_members").select("*").eq("id", victim["id"]).execute().data
    assert len(survivors) == 1, "the other workspace's roster row must survive"


def test_update_team_member_still_works_within_own_workspace(client, fake_db, workspace):
    mine = fake_db.table("team_members").insert({
        "workspace_id": workspace["id"],
        "name": "Alice",
        "role": "frontend",
        "weekly_capacity_hours": 40,
    }).execute().data[0]

    res = client.patch(
        f"/workspaces/{workspace['id']}/team/{mine['id']}",
        json={"name": "Alice Smith"},
    )

    assert res.status_code == 200
    assert res.json()["name"] == "Alice Smith"


def test_delete_team_member_still_works_within_own_workspace(client, fake_db, workspace):
    mine = fake_db.table("team_members").insert({
        "workspace_id": workspace["id"],
        "name": "Bob",
        "role": "backend",
        "weekly_capacity_hours": 40,
    }).execute().data[0]

    res = client.delete(f"/workspaces/{workspace['id']}/team/{mine['id']}")

    assert res.status_code == 204
    assert fake_db.table("team_members").select("*").eq("id", mine["id"]).execute().data == []
