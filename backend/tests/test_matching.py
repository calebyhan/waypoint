import pytest

from services.matching import (
    _create_proposal,
    _fuzzy_title_match,
    _is_rejected_pair,
    match_issue_to_task,
    match_pr_to_task,
)

WORKSPACE_ID = "ws-1"


def test_fuzzy_match_identical_titles_scores_one():
    assert _fuzzy_title_match("Add JWT refresh logic", "Add JWT refresh logic") == 1.0


def test_fuzzy_match_unrelated_titles_scores_low():
    score = _fuzzy_title_match("Add JWT refresh logic", "Fix CSS layout bug")
    assert score < 0.3


def test_fuzzy_match_partial_overlap_scores_between_zero_and_one():
    score = _fuzzy_title_match("Add JWT refresh logic", "Implement JWT refresh endpoint")
    assert 0.0 < score < 1.0


def test_rejected_pair_is_not_reproposed(fake_db):
    fake_db.table("match_proposals").insert({
        "workspace_id": WORKSPACE_ID,
        "task_id": "task-1",
        "github_issue_id": "issue-1",
        "status": "rejected",
    }).execute()

    assert _is_rejected_pair(fake_db, WORKSPACE_ID, "task-1", "issue-1", None) is True


def test_pending_pair_is_not_treated_as_rejected(fake_db):
    fake_db.table("match_proposals").insert({
        "workspace_id": WORKSPACE_ID,
        "task_id": "task-1",
        "github_issue_id": "issue-1",
        "status": "pending",
    }).execute()

    assert _is_rejected_pair(fake_db, WORKSPACE_ID, "task-1", "issue-1", None) is False


@pytest.mark.asyncio
async def test_pr_matches_via_closes_reference(fake_db):
    issue = fake_db.table("github_issues").insert({
        "workspace_id": WORKSPACE_ID,
        "number": 42,
        "title": "Add JWT refresh logic",
        "state": "open",
    }).execute().data[0]
    task = fake_db.table("tasks").insert({
        "workspace_id": WORKSPACE_ID,
        "title": "Implement JWT refresh",
        "github_issue_id": issue["id"],
    }).execute().data[0]

    pr_row = fake_db.table("github_prs").insert({
        "workspace_id": WORKSPACE_ID,
        "number": 55,
        "title": "Closes #42 - implement refresh",
        "state": "open",
    }).execute().data[0]

    proposal = await match_pr_to_task(fake_db, WORKSPACE_ID, pr_row, gemini_key=None)

    assert proposal is not None
    assert proposal["task_id"] == task["id"]
    assert proposal["similarity_score"] == 1.0


@pytest.mark.asyncio
async def test_pr_referencing_unlinked_issue_resurfaces_prior_accepted_task(fake_db):
    """After a manual unlink, a new PR referencing the same issue should
    surface the previously-linked task as a fresh pending proposal rather than
    silently auto-relinking or dropping the reference."""
    issue = fake_db.table("github_issues").insert({
        "workspace_id": WORKSPACE_ID, "number": 42, "title": "Add JWT refresh logic", "state": "open",
    }).execute().data[0]
    task = fake_db.table("tasks").insert({
        "workspace_id": WORKSPACE_ID, "title": "Implement JWT refresh",
    }).execute().data[0]
    fake_db.table("match_proposals").insert({
        "workspace_id": WORKSPACE_ID, "task_id": task["id"], "github_issue_id": issue["id"],
        "status": "accepted", "similarity_score": 1.0,
    }).execute()

    pr_row = fake_db.table("github_prs").insert({
        "workspace_id": WORKSPACE_ID, "number": 56, "title": "Closes #42 - retry", "state": "open",
    }).execute().data[0]

    proposal = await match_pr_to_task(fake_db, WORKSPACE_ID, pr_row, gemini_key=None)

    assert proposal is not None
    assert proposal["task_id"] == task["id"]
    assert proposal["status"] == "pending"


def test_create_proposal_dedupes_pending_pair_for_same_issue():
    from tests.fake_supabase import FakeSupabaseClient

    fake_db = FakeSupabaseClient()
    first = _create_proposal(fake_db, WORKSPACE_ID, "task-1", "issue-1", None, 0.8)
    second = _create_proposal(fake_db, WORKSPACE_ID, "task-1", "issue-1", None, 0.95)

    assert first["id"] == second["id"]
    rows = fake_db.table("match_proposals").select("*").eq("workspace_id", WORKSPACE_ID).execute().data
    assert len(rows) == 1
    assert rows[0]["similarity_score"] == 0.95


@pytest.mark.asyncio
async def test_match_issue_to_task_dedupes_when_called_twice(fake_db):
    """Simulates webhook + reconcile both discovering the same new issue and
    both triggering matching -- should not produce duplicate pending proposals."""
    fake_db.table("tasks").insert({
        "workspace_id": WORKSPACE_ID, "title": "Add JWT refresh logic",
    }).execute()
    issue_row = fake_db.table("github_issues").insert({
        "workspace_id": WORKSPACE_ID, "number": 1, "title": "Add JWT refresh logic", "state": "open",
    }).execute().data[0]

    await match_issue_to_task(fake_db, WORKSPACE_ID, issue_row, gemini_key=None)
    await match_issue_to_task(fake_db, WORKSPACE_ID, issue_row, gemini_key=None)

    proposals = fake_db.table("match_proposals").select("*").eq("workspace_id", WORKSPACE_ID).execute().data
    assert len(proposals) == 1


@pytest.mark.asyncio
async def test_pr_with_no_reference_and_no_fuzzy_match_returns_none(fake_db):
    fake_db.table("tasks").insert({
        "workspace_id": WORKSPACE_ID,
        "title": "Completely unrelated task name",
    }).execute()

    pr_row = fake_db.table("github_prs").insert({
        "workspace_id": WORKSPACE_ID,
        "number": 1,
        "title": "xyz",
        "state": "open",
    }).execute().data[0]

    proposal = await match_pr_to_task(fake_db, WORKSPACE_ID, pr_row, gemini_key=None)

    assert proposal is None
