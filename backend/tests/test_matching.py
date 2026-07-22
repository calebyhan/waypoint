from unittest.mock import AsyncMock

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


# --- Semantic (Gemini embedding) branch --------------------------------------


def _seed_semantic_fixture(fake_db):
    """A task whose title can't fuzzy-match the issue, forcing the semantic path."""
    task = fake_db.table("tasks").insert({
        "workspace_id": WORKSPACE_ID, "title": "Completely different wording here",
    }).execute().data[0]
    issue_row = fake_db.table("github_issues").insert({
        "workspace_id": WORKSPACE_ID, "number": 9, "title": "xyz qrs", "state": "open",
    }).execute().data[0]
    return task, issue_row


@pytest.mark.asyncio
async def test_semantic_match_used_when_fuzzy_score_below_threshold(fake_db, monkeypatch):
    task, issue_row = _seed_semantic_fixture(fake_db)
    fake_db.store.rpc_results["match_tasks_by_embedding"] = [{"id": task["id"], "similarity": 0.9}]
    monkeypatch.setattr("services.matching.generate_embedding", AsyncMock(return_value=[0.1, 0.2]))

    proposal = await match_issue_to_task(fake_db, WORKSPACE_ID, issue_row, gemini_key="fake-key")

    assert proposal is not None
    assert proposal["task_id"] == task["id"]
    assert proposal["similarity_score"] == 0.9


@pytest.mark.asyncio
async def test_semantic_match_respects_rejected_pairs(fake_db, monkeypatch):
    task, issue_row = _seed_semantic_fixture(fake_db)
    fake_db.table("match_proposals").insert({
        "workspace_id": WORKSPACE_ID, "task_id": task["id"],
        "github_issue_id": issue_row["id"], "status": "rejected",
    }).execute()
    fake_db.store.rpc_results["match_tasks_by_embedding"] = [{"id": task["id"], "similarity": 0.9}]
    monkeypatch.setattr("services.matching.generate_embedding", AsyncMock(return_value=[0.1]))

    proposal = await match_issue_to_task(fake_db, WORKSPACE_ID, issue_row, gemini_key="fake-key")

    assert proposal is None


@pytest.mark.asyncio
async def test_semantic_match_gemini_failure_returns_none_not_raise(fake_db, monkeypatch):
    _, issue_row = _seed_semantic_fixture(fake_db)
    monkeypatch.setattr(
        "services.matching.generate_embedding",
        AsyncMock(side_effect=Exception("gemini down")),
    )

    proposal = await match_issue_to_task(fake_db, WORKSPACE_ID, issue_row, gemini_key="fake-key")

    assert proposal is None  # degraded gracefully, no exception


@pytest.mark.asyncio
async def test_semantic_match_empty_rpc_result_returns_none(fake_db, monkeypatch):
    _, issue_row = _seed_semantic_fixture(fake_db)
    fake_db.store.rpc_results["match_tasks_by_embedding"] = []
    monkeypatch.setattr("services.matching.generate_embedding", AsyncMock(return_value=[0.1]))

    proposal = await match_issue_to_task(fake_db, WORKSPACE_ID, issue_row, gemini_key="fake-key")

    assert proposal is None


@pytest.mark.asyncio
async def test_match_issue_to_task_with_no_tasks_in_workspace_returns_none(fake_db, monkeypatch):
    embed = AsyncMock(return_value=[0.1])
    monkeypatch.setattr("services.matching.generate_embedding", embed)
    issue_row = {"id": "gi-1", "number": 1, "title": "Anything", "state": "open"}

    proposal = await match_issue_to_task(fake_db, WORKSPACE_ID, issue_row, gemini_key="fake-key")

    assert proposal is None
    embed.assert_not_awaited()  # early return before the semantic branch


@pytest.mark.asyncio
async def test_pr_body_with_multiple_issue_refs_skips_missing_ref(fake_db):
    """'Fixes #1, closes #2' where #1 doesn't exist locally: the loop must
    continue past the missing ref and match via #2."""
    issue2 = fake_db.table("github_issues").insert({
        "workspace_id": WORKSPACE_ID, "number": 2, "title": "Second", "state": "open",
    }).execute().data[0]
    task = fake_db.table("tasks").insert({
        "workspace_id": WORKSPACE_ID, "title": "Linked task", "github_issue_id": issue2["id"],
    }).execute().data[0]
    pr_row = fake_db.table("github_prs").insert({
        "workspace_id": WORKSPACE_ID, "number": 77,
        "title": "Fixes #1, closes #2", "state": "open",
    }).execute().data[0]

    proposal = await match_pr_to_task(fake_db, WORKSPACE_ID, pr_row, gemini_key=None)

    assert proposal is not None
    assert proposal["task_id"] == task["id"]
