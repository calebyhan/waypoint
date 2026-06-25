import pytest

from services.matching import _fuzzy_title_match, _is_rejected_pair, match_pr_to_task

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
        "linked_task_id": "task-1",
    }).execute().data[0]

    pr_row = fake_db.table("github_prs").insert({
        "workspace_id": WORKSPACE_ID,
        "number": 55,
        "title": "Closes #42 - implement refresh",
        "state": "open",
    }).execute().data[0]

    proposal = await match_pr_to_task(fake_db, WORKSPACE_ID, pr_row, gemini_key=None)

    assert proposal is not None
    assert proposal["task_id"] == "task-1"
    assert proposal["similarity_score"] == 1.0
    assert issue["number"] == 42


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
