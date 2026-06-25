def seed_task(fake_db, workspace_id, **overrides):
    epic = fake_db.table("epics").insert({"workspace_id": workspace_id, "title": "Auth", "sort_order": 0}).execute().data[0]
    row = {"workspace_id": workspace_id, "epic_id": epic["id"], "title": "Implement JWT login", "status": "open", "priority": "p0"}
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
    task = seed_task(fake_db, workspace["id"])

    res = client.patch(f"/workspaces/{workspace['id']}/tasks/{task['id']}/assignee", json={"assignee": "octocat"})

    assert res.status_code == 200
    assert res.json()["assignee"] == "octocat"


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
    updated_issue = fake_db.table("github_issues").select("*").eq("id", issue["id"]).single().execute().data
    assert updated_issue["linked_task_id"] == task["id"]


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
    updated_issue = fake_db.table("github_issues").select("*").eq("id", issue["id"]).single().execute().data
    assert updated_issue.get("linked_task_id") is None


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
