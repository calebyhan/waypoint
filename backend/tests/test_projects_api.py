def seed_epic_and_task(fake_db, workspace_id, **task_overrides):
    epic = fake_db.table("epics").insert({"workspace_id": workspace_id, "title": "Auth", "sort_order": 0}).execute().data[0]
    task_row = {
        "workspace_id": workspace_id,
        "epic_id": epic["id"],
        "title": "Implement JWT login",
        "priority": "p0",
        "status": "open",
        "version": 1,
        "sort_order": 0,
    }
    task_row.update(task_overrides)
    task = fake_db.table("tasks").insert(task_row).execute().data[0]
    return epic, task


def test_update_task_succeeds_with_matching_version(client, fake_db, workspace):
    _, task = seed_epic_and_task(fake_db, workspace["id"])

    res = client.patch(
        f"/workspaces/{workspace['id']}/tasks/{task['id']}",
        json={"title": "Implement JWT login (updated)", "version": 1},
    )

    assert res.status_code == 200
    assert res.json()["version"] == 2
    assert res.json()["title"] == "Implement JWT login (updated)"


def test_update_task_with_stale_version_returns_conflict(client, fake_db, workspace):
    _, task = seed_epic_and_task(fake_db, workspace["id"])

    # First edit bumps version to 2.
    client.patch(f"/workspaces/{workspace['id']}/tasks/{task['id']}", json={"title": "Edit A", "version": 1})

    # A second PM still holding version 1 tries to save -- should conflict.
    res = client.patch(
        f"/workspaces/{workspace['id']}/tasks/{task['id']}",
        json={"title": "Edit B (stale)", "version": 1},
    )

    assert res.status_code == 409


def test_approve_plan_materializes_decomposition_into_tasks(client, fake_db, workspace):
    fake_db.table("ingestions").insert({
        "workspace_id": workspace["id"],
        "content_hash": "abc",
        "raw_content": "some prd",
        "decomposition": {
            "epics": [
                {
                    "title": "Authentication",
                    "tasks": [
                        {
                            "title": "Implement JWT login", "description": "desc",
                            "motivation": "Unblocks all authenticated routes",
                            "deliverables": ["POST /api/auth/login"],
                            "important_notes": ["Token expiry is 24h"],
                            "estimated_days": 2, "priority": "p0",
                        },
                        {"title": "Implement JWT logout", "description": "desc", "estimated_days": 1, "priority": "p1"},
                    ],
                }
            ]
        },
    }).execute()

    res = client.post(f"/workspaces/{workspace['id']}/plan/approve")

    assert res.status_code == 200
    epics = fake_db.table("epics").select("*").eq("workspace_id", workspace["id"]).execute().data
    tasks = fake_db.table("tasks").select("*").eq("workspace_id", workspace["id"]).execute().data
    assert len(epics) == 1
    assert len(tasks) == 2
    assert all(t["status"] == "open" for t in tasks)
    login_task = next(t for t in tasks if t["title"] == "Implement JWT login")
    assert login_task["motivation"] == "Unblocks all authenticated routes"
    assert login_task["deliverables"] == ["POST /api/auth/login"]
    assert login_task["important_notes"] == ["Token expiry is 24h"]


def test_approve_plan_without_any_plan_returns_400(client, workspace):
    res = client.post(f"/workspaces/{workspace['id']}/plan/approve")
    assert res.status_code == 400


def test_split_task_creates_subtasks_and_removes_original(client, fake_db, workspace):
    epic, task = seed_epic_and_task(fake_db, workspace["id"])

    res = client.post(
        f"/workspaces/{workspace['id']}/tasks/{task['id']}/split",
        json={
            "subtasks": [
                {"epic_id": epic["id"], "title": "Login: backend endpoint", "priority": "p0"},
                {"epic_id": epic["id"], "title": "Login: frontend form", "priority": "p1"},
            ]
        },
    )

    assert res.status_code == 200
    assert len(res.json()["new_tasks"]) == 2

    remaining = fake_db.table("tasks").select("*").eq("workspace_id", workspace["id"]).execute().data
    titles = {t["title"] for t in remaining}
    assert "Implement JWT login" not in titles
    assert "Login: backend endpoint" in titles
    assert "Login: frontend form" in titles


def test_merge_tasks_combines_estimated_days(client, fake_db, workspace):
    epic, task_a = seed_epic_and_task(fake_db, workspace["id"], title="Part A", estimated_days=1)
    task_b = fake_db.table("tasks").insert({
        "workspace_id": workspace["id"],
        "epic_id": epic["id"],
        "title": "Part B",
        "priority": "p0",
        "status": "open",
        "estimated_days": 2,
        "version": 1,
    }).execute().data[0]

    res = client.post(
        f"/workspaces/{workspace['id']}/tasks/merge",
        json={"task_ids": [task_a["id"], task_b["id"]], "merged_title": "Part A+B"},
    )

    assert res.status_code == 200
    assert res.json()["estimated_days"] == 3

    remaining = fake_db.table("tasks").select("*").eq("workspace_id", workspace["id"]).execute().data
    assert len(remaining) == 1
    assert remaining[0]["title"] == "Part A+B"
