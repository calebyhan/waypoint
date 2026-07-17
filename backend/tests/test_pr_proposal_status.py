"""Regression tests for the premature in_review status flip.

handle_pr_change used to bump a task to in_review the moment a match
*proposal* was created -- before the PM accepted it -- and a rejection never
reverted the status. Status must only change when the PM accepts."""

from services.github_sync import handle_pr_change


def _seed(fake_db, workspace):
    epic = fake_db.table("epics").insert({
        "workspace_id": workspace["id"], "title": "E", "sort_order": 0,
    }).execute().data[0]
    task = fake_db.table("tasks").insert({
        "workspace_id": workspace["id"],
        "epic_id": epic["id"],
        "title": "Implement login page",
        "status": "open",
        "version": 1,
        "sort_order": 0,
    }).execute().data[0]
    pr = fake_db.table("github_prs").insert({
        "workspace_id": workspace["id"],
        "github_id": 999,
        "number": 7,
        "title": "Implement login page",
        "state": "open",
        "merged": False,
    }).execute().data[0]
    return task, pr


async def test_pr_match_proposal_does_not_change_task_status(fake_db, workspace):
    task, pr = _seed(fake_db, workspace)

    await handle_pr_change(fake_db, workspace, pr, "opened", None, is_new=True)

    proposals = fake_db.store.rows("match_proposals")
    assert len(proposals) == 1
    assert proposals[0]["status"] == "pending"
    assert proposals[0]["task_id"] == task["id"]

    refreshed = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert refreshed["status"] == "open"  # not in_review until the PM accepts


async def test_rejecting_pr_proposal_leaves_task_status_unchanged(client, fake_db, workspace):
    task, pr = _seed(fake_db, workspace)
    await handle_pr_change(fake_db, workspace, pr, "opened", None, is_new=True)
    proposal = fake_db.store.rows("match_proposals")[0]

    res = client.post(
        f"/workspaces/{workspace['id']}/match-proposals/{proposal['id']}/decide",
        json={"accept": False},
    )

    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    refreshed = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert refreshed["status"] == "open"  # never stuck at in_review


async def test_accepting_pr_proposal_sets_in_review_and_links_pr(client, fake_db, workspace):
    task, pr = _seed(fake_db, workspace)
    await handle_pr_change(fake_db, workspace, pr, "opened", None, is_new=True)
    proposal = fake_db.store.rows("match_proposals")[0]

    res = client.post(
        f"/workspaces/{workspace['id']}/match-proposals/{proposal['id']}/decide",
        json={"accept": True},
    )

    assert res.status_code == 200
    refreshed = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert refreshed["status"] == "in_review"
    linked_pr = fake_db.table("github_prs").select("*").eq("id", pr["id"]).single().execute().data
    assert linked_pr["linked_task_id"] == task["id"]
