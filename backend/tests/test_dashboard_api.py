def seed_task(fake_db, workspace_id, **overrides):
    epic = fake_db.table("epics").insert({"workspace_id": workspace_id, "title": "Auth", "sort_order": 0}).execute().data[0]
    row = {
        "workspace_id": workspace_id, "epic_id": epic["id"], "title": "Implement JWT login",
        "status": "open", "priority": "p0", "github_conflict": False,
    }
    row.update(overrides)
    return fake_db.table("tasks").insert(row).execute().data[0]


def test_update_task_status(client, fake_db, workspace):
    task = seed_task(fake_db, workspace["id"])

    res = client.patch(f"/workspaces/{workspace['id']}/tasks/{task['id']}/status", json={"status": "done"})

    assert res.status_code == 200
    assert res.json()["status"] == "done"


def test_update_task_status_rejects_invalid_value(client, fake_db, workspace):
    task = seed_task(fake_db, workspace["id"])

    res = client.patch(f"/workspaces/{workspace['id']}/tasks/{task['id']}/status", json={"status": "bogus"})

    assert res.status_code == 400


def test_update_task_assignee(client, fake_db, workspace):
    task = seed_task(fake_db, workspace["id"], version=1)

    res = client.patch(f"/workspaces/{workspace['id']}/tasks/{task['id']}/assignee", json={"assignee": "octocat"})

    assert res.status_code == 200
    assert res.json()["assignee"] == "octocat"
    assert res.json()["version"] == 2


def test_assignee_update_bumps_version_so_stale_edit_conflicts(client, fake_db, workspace):
    task = seed_task(fake_db, workspace["id"], version=1)

    client.patch(f"/workspaces/{workspace['id']}/tasks/{task['id']}/assignee", json={"assignee": "octocat"})
    res = client.patch(
        f"/workspaces/{workspace['id']}/tasks/{task['id']}",
        json={"title": "Edited by human", "version": 1},
    )

    assert res.status_code == 409


def test_schedule_update_bumps_version(client, fake_db, workspace):
    task = seed_task(fake_db, workspace["id"], version=1)

    res = client.patch(
        f"/workspaces/{workspace['id']}/tasks/{task['id']}/schedule",
        json={"start_date": "2026-01-01", "end_date": "2026-01-05"},
    )

    assert res.status_code == 200
    assert res.json()["version"] == 2


def test_accepting_issue_proposal_links_issue_to_task(client, fake_db, workspace):
    task = seed_task(fake_db, workspace["id"])
    issue = fake_db.table("github_issues").insert({
        "workspace_id": workspace["id"], "number": 42, "title": "Add JWT refresh", "state": "open",
    }).execute().data[0]
    proposal = fake_db.table("match_proposals").insert({
        "workspace_id": workspace["id"], "task_id": task["id"], "github_issue_id": issue["id"],
        "status": "pending", "similarity_score": 0.9,
    }).execute().data[0]

    res = client.post(f"/workspaces/{workspace['id']}/match-proposals/{proposal['id']}/decide", json={"accept": True})

    assert res.status_code == 200
    assert res.json()["status"] == "accepted"
    updated_task = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated_task["github_issue_id"] == issue["id"]


def test_accepting_pr_proposal_sets_task_in_review(client, fake_db, workspace):
    task = seed_task(fake_db, workspace["id"])
    pr = fake_db.table("github_prs").insert({
        "workspace_id": workspace["id"], "number": 55, "title": "jwt-refresh", "state": "open", "merged": False,
    }).execute().data[0]
    proposal = fake_db.table("match_proposals").insert({
        "workspace_id": workspace["id"], "task_id": task["id"], "github_pr_id": pr["id"],
        "status": "pending", "similarity_score": 0.85,
    }).execute().data[0]

    res = client.post(f"/workspaces/{workspace['id']}/match-proposals/{proposal['id']}/decide", json={"accept": True})

    assert res.status_code == 200
    updated_task = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated_task["status"] == "in_review"


def test_rejecting_proposal_does_not_link(client, fake_db, workspace):
    task = seed_task(fake_db, workspace["id"])
    issue = fake_db.table("github_issues").insert({
        "workspace_id": workspace["id"], "number": 1, "title": "Unrelated", "state": "open",
    }).execute().data[0]
    proposal = fake_db.table("match_proposals").insert({
        "workspace_id": workspace["id"], "task_id": task["id"], "github_issue_id": issue["id"],
        "status": "pending", "similarity_score": 0.4,
    }).execute().data[0]

    res = client.post(f"/workspaces/{workspace['id']}/match-proposals/{proposal['id']}/decide", json={"accept": False})

    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    updated_task = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated_task.get("github_issue_id") is None


def test_marking_task_done_while_linked_issue_open_flags_conflict(client, fake_db, workspace):
    issue = fake_db.table("github_issues").insert({
        "workspace_id": workspace["id"], "number": 7, "title": "Bug", "state": "open",
    }).execute().data[0]
    task = seed_task(fake_db, workspace["id"], github_issue_id=issue["id"])

    res = client.patch(f"/workspaces/{workspace['id']}/tasks/{task['id']}/status", json={"status": "done"})

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "done"
    assert body["github_conflict"] is True
    assert "#7" in body["github_conflict_reason"]


def test_marking_task_done_with_issue_already_closed_does_not_flag(client, fake_db, workspace):
    issue = fake_db.table("github_issues").insert({
        "workspace_id": workspace["id"], "number": 8, "title": "Bug", "state": "closed",
    }).execute().data[0]
    task = seed_task(fake_db, workspace["id"], github_issue_id=issue["id"])

    res = client.patch(f"/workspaces/{workspace['id']}/tasks/{task['id']}/status", json={"status": "done"})

    assert res.status_code == 200
    assert res.json()["github_conflict"] is False


def test_unlink_issue_clears_task_pointer(client, fake_db, workspace):
    issue = fake_db.table("github_issues").insert({
        "workspace_id": workspace["id"], "number": 9, "title": "Bug", "state": "open",
    }).execute().data[0]
    task = seed_task(fake_db, workspace["id"], github_issue_id=issue["id"])

    res = client.delete(f"/workspaces/{workspace['id']}/tasks/{task['id']}/github-link?kind=issue")

    assert res.status_code == 200
    updated = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated["github_issue_id"] is None


def test_unlink_pr_only_clears_that_pr(client, fake_db, workspace):
    task = seed_task(fake_db, workspace["id"])
    pr_a = fake_db.table("github_prs").insert({
        "workspace_id": workspace["id"], "number": 1, "title": "PR A", "state": "open", "merged": False,
        "linked_task_id": task["id"],
    }).execute().data[0]
    pr_b = fake_db.table("github_prs").insert({
        "workspace_id": workspace["id"], "number": 2, "title": "PR B", "state": "open", "merged": False,
        "linked_task_id": task["id"],
    }).execute().data[0]

    res = client.delete(
        f"/workspaces/{workspace['id']}/tasks/{task['id']}/github-link?kind=pr&github_pr_id={pr_a['id']}"
    )

    assert res.status_code == 200
    updated_a = fake_db.table("github_prs").select("*").eq("id", pr_a["id"]).single().execute().data
    updated_b = fake_db.table("github_prs").select("*").eq("id", pr_b["id"]).single().execute().data
    assert updated_a["linked_task_id"] is None
    assert updated_b["linked_task_id"] == task["id"]


def test_resolve_conflict_keep_github_reverts_status(client, fake_db, workspace):
    issue = fake_db.table("github_issues").insert({
        "workspace_id": workspace["id"], "number": 7, "title": "Bug", "state": "open",
    }).execute().data[0]
    task = seed_task(
        fake_db, workspace["id"], github_issue_id=issue["id"], status="done",
        github_conflict=True, github_conflict_reason="conflict",
    )

    res = client.post(
        f"/workspaces/{workspace['id']}/tasks/{task['id']}/resolve-conflict",
        json={"resolution": "keep_github"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "open"
    assert body["github_conflict"] is False


def test_dashboard_aggregates_epic_progress(client, fake_db, workspace):
    epic = fake_db.table("epics").insert({"workspace_id": workspace["id"], "title": "Auth", "sort_order": 0}).execute().data[0]
    fake_db.table("tasks").insert({"workspace_id": workspace["id"], "epic_id": epic["id"], "title": "A", "status": "done", "priority": "p0"}).execute()
    fake_db.table("tasks").insert({"workspace_id": workspace["id"], "epic_id": epic["id"], "title": "B", "status": "open", "priority": "p1"}).execute()

    res = client.get(f"/workspaces/{workspace['id']}/dashboard")

    assert res.status_code == 200
    body = res.json()
    assert len(body["epics"]) == 1
    assert body["epics"][0]["total_tasks"] == 2
    assert body["epics"][0]["done_tasks"] == 1
    assert body["epics"][0]["progress_pct"] == 50
