from datetime import datetime, timedelta, timezone

from services.insights import generate_insights

WORKSPACE_ID = "ws-1"


def iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def seed_task(fake_db, **overrides):
    row = {
        "id": "task-1",
        "workspace_id": WORKSPACE_ID,
        "title": "Implement token refresh",
        "status": "open",
        "priority": "p0",
        "assignee": "alice",
        "dependencies": [],
        "created_at": iso(0),
    }
    row.update(overrides)
    fake_db.table("tasks").insert(row).execute()
    return row


def test_blocker_flagged_when_open_too_long_with_no_pr(fake_db):
    seed_task(fake_db, created_at=iso(5))

    insights = generate_insights(fake_db, WORKSPACE_ID)

    assert any(i["type"] == "blocker" for i in insights)


def test_no_blocker_when_task_is_recent(fake_db):
    seed_task(fake_db, created_at=iso(1))

    insights = generate_insights(fake_db, WORKSPACE_ID)

    assert not any(i["type"] == "blocker" for i in insights)


def test_unassigned_task_is_flagged(fake_db):
    seed_task(fake_db, assignee=None, created_at=iso(1))

    insights = generate_insights(fake_db, WORKSPACE_ID)

    assert any(i["type"] == "unassigned" for i in insights)


def test_dependency_violation_when_blocking_task_open(fake_db):
    seed_task(fake_db, id="dep-task", title="Set up auth middleware", status="open", created_at=iso(0))
    seed_task(
        fake_db,
        id="task-1",
        title="Add refresh endpoint",
        status="in_review",
        dependencies=["dep-task"],
        created_at=iso(0),
    )

    insights = generate_insights(fake_db, WORKSPACE_ID)

    violations = [i for i in insights if i["type"] == "dependency_violation"]
    assert len(violations) == 1
    assert "Set up auth middleware" in violations[0]["message"]


def test_done_tasks_are_skipped_entirely(fake_db):
    seed_task(fake_db, status="done", assignee=None, created_at=iso(10))

    insights = generate_insights(fake_db, WORKSPACE_ID)

    assert insights == []


def test_partial_signal_when_issue_closed_but_pr_not_merged(fake_db):
    seed_task(fake_db, created_at=iso(1))
    fake_db.table("github_issues").insert({
        "workspace_id": WORKSPACE_ID,
        "linked_task_id": "task-1",
        "state": "closed",
        "number": 42,
    }).execute()

    insights = generate_insights(fake_db, WORKSPACE_ID)

    assert any(i["type"] == "partial_signal" for i in insights)


def test_insights_sorted_by_priority_p0_first(fake_db):
    seed_task(fake_db, id="t-p2", priority="p2", assignee=None, created_at=iso(1))
    seed_task(fake_db, id="t-p0", priority="p0", assignee=None, created_at=iso(1))

    insights = generate_insights(fake_db, WORKSPACE_ID)

    priorities = [i["priority"] for i in insights]
    assert priorities.index("p0") < priorities.index("p2")


# --- stale_pr insight ---------------------------------------------------------


def seed_pr(fake_db, **overrides):
    row = {
        "workspace_id": WORKSPACE_ID,
        "number": 99,
        "title": "Long-lived PR",
        "state": "open",
        "merged": False,
        "linked_task_id": None,
        "created_at": iso(10),
    }
    row.update(overrides)
    fake_db.table("github_prs").insert(row).execute()
    return row


def test_stale_pr_flagged_when_open_more_than_seven_days(fake_db):
    seed_pr(fake_db, created_at=iso(10))

    insights = generate_insights(fake_db, WORKSPACE_ID)

    stale = [i for i in insights if i["type"] == "stale_pr"]
    assert len(stale) == 1
    assert stale[0]["priority"] == "p2"  # no linked task -> default priority
    assert "#99" in stale[0]["message"]


def test_stale_pr_uses_linked_tasks_priority_when_present(fake_db):
    task = seed_task(fake_db, priority="p0", created_at=iso(1))
    seed_pr(fake_db, created_at=iso(10), linked_task_id=task["id"])

    insights = generate_insights(fake_db, WORKSPACE_ID)

    stale = [i for i in insights if i["type"] == "stale_pr"]
    assert len(stale) == 1
    assert stale[0]["priority"] == "p0"
    assert stale[0]["task_id"] == task["id"]


def test_no_stale_pr_when_pr_is_recent(fake_db):
    seed_pr(fake_db, created_at=iso(1))

    insights = generate_insights(fake_db, WORKSPACE_ID)

    assert not any(i["type"] == "stale_pr" for i in insights)


def test_merged_or_closed_prs_are_never_flagged_stale(fake_db):
    seed_pr(fake_db, state="closed", created_at=iso(30))

    insights = generate_insights(fake_db, WORKSPACE_ID)

    assert not any(i["type"] == "stale_pr" for i in insights)


async def test_generate_insights_for_all_workspaces_isolates_failures(fake_db, monkeypatch):
    from services.insights import generate_insights_for_all_workspaces

    fake_db.seed("workspaces", [
        {"id": "ws-boom", "state": "active"},
        {"id": "ws-ok", "state": "active"},
        {"id": "ws-archived", "state": "archived"},
    ])
    seen = []

    def fake_generate(db, workspace_id):
        if workspace_id == "ws-boom":
            raise RuntimeError("simulated")
        seen.append(workspace_id)

    monkeypatch.setattr("services.insights.generate_insights", fake_generate)

    await generate_insights_for_all_workspaces(fake_db)  # must not raise

    assert seen == ["ws-ok"]  # archived workspaces are skipped, failures isolated
