import pytest

from services.github_sync import bump_task, handle_issue_change, upsert_issue, upsert_pr

WORKSPACE = {"id": "ws-1"}


def test_bump_task_increments_version(fake_db):
    task = fake_db.table("tasks").insert({"workspace_id": "ws-1", "title": "T", "version": 1}).execute().data[0]

    updated = bump_task(fake_db, task["id"], {"status": "done"})

    assert updated["status"] == "done"
    assert updated["version"] == 2


def test_bump_task_lets_stale_client_patch_conflict(client, fake_db, workspace):
    """A GitHub-driven write should bump version so a human's later PATCH,
    still holding the version they last loaded, correctly 409s instead of
    silently stomping the GitHub-driven change."""
    epic = fake_db.table("epics").insert({"workspace_id": workspace["id"], "title": "Epic"}).execute().data[0]
    task = fake_db.table("tasks").insert({
        "workspace_id": workspace["id"], "epic_id": epic["id"], "title": "T", "status": "open", "version": 1,
    }).execute().data[0]

    bump_task(fake_db, task["id"], {"status": "in_review"})  # simulates a webhook-driven PR match

    res = client.patch(
        f"/workspaces/{workspace['id']}/tasks/{task['id']}",
        json={"title": "Edited by human", "version": 1},
    )

    assert res.status_code == 409


@pytest.mark.asyncio
async def test_upsert_issue_is_idempotent(fake_db):
    issue = {"id": 1, "number": 1, "title": "Bug", "state": "open"}

    first = await upsert_issue(fake_db, "ws-1", issue)
    second = await upsert_issue(fake_db, "ws-1", {**issue, "title": "Bug (edited)"})

    assert first["id"] == second["id"]
    rows = fake_db.table("github_issues").select("*").eq("workspace_id", "ws-1").execute().data
    assert len(rows) == 1
    assert rows[0]["title"] == "Bug (edited)"


@pytest.mark.asyncio
async def test_upsert_pr_is_idempotent(fake_db):
    pr = {"id": 10, "number": 5, "title": "Fix", "state": "open", "merged": False}

    await upsert_pr(fake_db, "ws-1", pr)
    await upsert_pr(fake_db, "ws-1", {**pr, "state": "closed", "merged": True})

    rows = fake_db.table("github_prs").select("*").eq("workspace_id", "ws-1").execute().data
    assert len(rows) == 1
    assert rows[0]["merged"] is True


@pytest.mark.asyncio
async def test_issue_deleted_marks_state_instead_of_removing_row(fake_db):
    saved = fake_db.table("github_issues").insert({
        "workspace_id": "ws-1", "github_id": 1, "number": 1, "title": "Bug", "state": "open",
    }).execute().data[0]

    await handle_issue_change(fake_db, WORKSPACE, saved, "deleted", None, is_new=False)

    row = fake_db.table("github_issues").select("*").eq("id", saved["id"]).single().execute().data
    assert row is not None
    assert row["state"] == "deleted"


@pytest.mark.asyncio
async def test_reopened_triggers_matching_only_when_unlinked(fake_db, monkeypatch):
    called = []

    async def fake_match(db, workspace_id, issue_row, gemini_key):
        called.append(issue_row["id"])
        return None

    monkeypatch.setattr("services.github_sync.match_issue_to_task", fake_match)

    saved_unlinked = fake_db.table("github_issues").insert({
        "workspace_id": "ws-1", "github_id": 1, "number": 1, "title": "Bug", "state": "open",
    }).execute().data[0]
    await handle_issue_change(fake_db, WORKSPACE, saved_unlinked, "reopened", None, is_new=False)
    assert saved_unlinked["id"] in called

    saved_linked = fake_db.table("github_issues").insert({
        "workspace_id": "ws-1", "github_id": 2, "number": 2, "title": "Other", "state": "open",
    }).execute().data[0]
    fake_db.table("tasks").insert({
        "workspace_id": "ws-1", "title": "Task", "status": "done", "github_issue_id": saved_linked["id"],
    }).execute()
    called.clear()
    await handle_issue_change(fake_db, WORKSPACE, saved_linked, "reopened", None, is_new=False)
    assert called == []
