from services.github_sync import recompute_task_done_state

WORKSPACE_ID = "ws-1"


def _make_task(fake_db, status, github_issue_id=None):
    return fake_db.table("tasks").insert({
        "workspace_id": WORKSPACE_ID, "title": "Task", "status": status, "github_issue_id": github_issue_id,
    }).execute().data[0]


def _make_issue(fake_db, state, number=1):
    return fake_db.table("github_issues").insert({
        "workspace_id": WORKSPACE_ID, "github_id": number, "number": number, "title": "Issue", "state": state,
    }).execute().data[0]


def test_issue_closed_with_no_linked_pr_marks_task_done(fake_db):
    issue = _make_issue(fake_db, "closed")
    task = _make_task(fake_db, "open", issue["id"])

    recompute_task_done_state(fake_db, task["id"])

    updated = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated["status"] == "done"


def test_issue_closed_with_merged_pr_marks_task_done(fake_db):
    issue = _make_issue(fake_db, "closed")
    task = _make_task(fake_db, "in_review", issue["id"])
    fake_db.table("github_prs").insert({
        "workspace_id": WORKSPACE_ID, "number": 1, "title": "PR", "state": "closed", "merged": True,
        "linked_task_id": task["id"],
    }).execute()

    recompute_task_done_state(fake_db, task["id"])

    updated = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated["status"] == "done"


def test_reopened_issue_reverts_done_task(fake_db):
    issue = _make_issue(fake_db, "open")
    task = _make_task(fake_db, "done", issue["id"])

    recompute_task_done_state(fake_db, task["id"])

    updated = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated["status"] == "open"
    assert updated["github_conflict"] is False


def test_pr_closed_unmerged_reverts_in_review_task_to_open(fake_db):
    issue = _make_issue(fake_db, "open")
    task = _make_task(fake_db, "in_review", issue["id"])
    fake_db.table("github_prs").insert({
        "workspace_id": WORKSPACE_ID, "number": 1, "title": "PR", "state": "closed", "merged": False,
        "linked_task_id": task["id"],
    }).execute()

    recompute_task_done_state(fake_db, task["id"])

    updated = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated["status"] == "open"


def test_recompute_favors_github_state_even_when_task_is_done(fake_db):
    """recompute_task_done_state is only called from GitHub-driven events, so it
    always lets GitHub's open/closed state win -- unlike the API-level conflict
    check in dashboard.py's update_task_status (see test_dashboard_api.py),
    which is the only place a done-while-open collision gets flagged instead
    of silently reverted."""
    issue = _make_issue(fake_db, "open", number=99)
    task = _make_task(fake_db, "done", issue["id"])

    recompute_task_done_state(fake_db, task["id"])

    updated = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated["status"] == "open"
    assert updated["github_conflict"] is False
