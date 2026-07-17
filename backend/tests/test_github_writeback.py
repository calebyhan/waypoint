from unittest.mock import AsyncMock

import httpx
import pytest

from services.github_writeback import create_issue_for_task, drain_outbox, update_issue_for_task

WORKSPACE = {"id": "ws-1", "owner_id": "user-1", "repo_owner": "acme", "repo_name": "widgets"}


@pytest.mark.asyncio
async def test_create_issue_for_task_success(fake_db, monkeypatch):
    task = fake_db.table("tasks").insert({
        "workspace_id": "ws-1", "title": "Add login", "description": "desc",
    }).execute().data[0]

    fake_create = AsyncMock(return_value={
        "id": 1, "number": 10, "title": "Add login", "state": "open", "body": "desc",
        "html_url": "https://github.com/acme/widgets/issues/10", "updated_at": "2026-01-01T00:00:00Z",
    })
    monkeypatch.setattr("services.github_writeback.create_issue", fake_create)

    await create_issue_for_task(fake_db, WORKSPACE, task, "tok")

    fake_create.assert_awaited_once()
    updated_task = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated_task["github_issue_id"] is not None
    issue = fake_db.table("github_issues").select("*").eq("id", updated_task["github_issue_id"]).single().execute().data
    assert issue["number"] == 10


@pytest.mark.asyncio
async def test_create_issue_for_task_failure_queues_outbox(fake_db, monkeypatch):
    task = fake_db.table("tasks").insert({"workspace_id": "ws-1", "title": "Add login"}).execute().data[0]

    fake_create = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))
    monkeypatch.setattr("services.github_writeback.create_issue", fake_create)

    await create_issue_for_task(fake_db, WORKSPACE, task, "tok")

    outbox = fake_db.table("github_write_outbox").select("*").eq("task_id", task["id"]).execute().data
    assert len(outbox) == 1
    assert outbox[0]["kind"] == "create_issue"
    updated_task = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated_task.get("github_issue_id") is None


@pytest.mark.asyncio
async def test_update_issue_for_task_success(fake_db, monkeypatch):
    issue = fake_db.table("github_issues").insert({
        "workspace_id": "ws-1", "github_id": 1, "number": 10, "title": "Old title", "state": "open",
    }).execute().data[0]
    task = fake_db.table("tasks").insert({
        "workspace_id": "ws-1", "title": "New title", "description": "new desc", "github_issue_id": issue["id"],
    }).execute().data[0]

    fake_update = AsyncMock(return_value={"title": "New title", "body": "new desc", "state": "open"})
    monkeypatch.setattr("services.github_writeback.update_issue", fake_update)

    await update_issue_for_task(fake_db, WORKSPACE, task, "tok")

    updated_issue = fake_db.table("github_issues").select("*").eq("id", issue["id"]).single().execute().data
    assert updated_issue["title"] == "New title"


@pytest.mark.asyncio
async def test_drain_outbox_retries_and_succeeds(fake_db, monkeypatch):
    fake_db.table("workspaces").insert({
        "id": "ws-1", "name": "Test", "owner_id": "user-1", "state": "active",
        "repo_owner": "acme", "repo_name": "widgets", "webhook_secret": "shh",
    }).execute()
    task = fake_db.table("tasks").insert({"workspace_id": "ws-1", "title": "T", "description": "d"}).execute().data[0]
    fake_db.table("github_write_outbox").insert({
        "workspace_id": "ws-1", "task_id": task["id"], "kind": "create_issue",
        "payload": {"title": "T", "body": "d"}, "attempts": 1, "last_error": "boom",
    }).execute()

    monkeypatch.setattr("services.github.get_github_token", lambda db, uid: "tok")
    fake_create = AsyncMock(return_value={
        "id": 1, "number": 1, "title": "T", "state": "open", "body": "d",
        "html_url": "https://x", "updated_at": "2026-01-01T00:00:00Z",
    })
    monkeypatch.setattr("services.github_writeback.create_issue", fake_create)

    await drain_outbox(fake_db)

    outbox = fake_db.table("github_write_outbox").select("*").eq("task_id", task["id"]).execute().data
    assert outbox[0]["completed_at"] is not None
    updated_task = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated_task["github_issue_id"] is not None


@pytest.mark.asyncio
async def test_drain_outbox_gives_up_after_max_attempts(fake_db, monkeypatch):
    fake_db.table("workspaces").insert({
        "id": "ws-1", "name": "Test", "owner_id": "user-1", "state": "active",
        "repo_owner": "acme", "repo_name": "widgets", "webhook_secret": "shh",
    }).execute()
    task = fake_db.table("tasks").insert({"workspace_id": "ws-1", "title": "T"}).execute().data[0]
    fake_db.table("github_write_outbox").insert({
        "workspace_id": "ws-1", "task_id": task["id"], "kind": "update_issue",
        "payload": {"issue_number": 1, "title": "T", "body": None}, "attempts": 9, "last_error": "boom",
    }).execute()

    monkeypatch.setattr("services.github.get_github_token", lambda db, uid: "tok")
    monkeypatch.setattr(
        "services.github_writeback.update_issue",
        AsyncMock(side_effect=httpx.ConnectTimeout("still down")),
    )

    await drain_outbox(fake_db)

    outbox = fake_db.table("github_write_outbox").select("*").eq("task_id", task["id"]).execute().data
    assert outbox[0]["attempts"] == 10
    assert outbox[0]["completed_at"] is not None
    updated_task = fake_db.table("tasks").select("*").eq("id", task["id"]).single().execute().data
    assert updated_task["github_sync_error"] is not None


# --- sync_task_status_to_github ----------------------------------------------


def _seed_linked_issue_and_task(fake_db, issue_state="open"):
    issue = fake_db.table("github_issues").insert({
        "workspace_id": "ws-1", "github_id": 5, "number": 12, "title": "Bug", "state": issue_state,
    }).execute().data[0]
    task = fake_db.table("tasks").insert({
        "workspace_id": "ws-1", "title": "Fix bug", "github_issue_id": issue["id"],
    }).execute().data[0]
    return issue, task


@pytest.mark.asyncio
async def test_sync_task_status_to_github_close_success(fake_db, monkeypatch):
    from services.github_writeback import sync_task_status_to_github

    issue, task = _seed_linked_issue_and_task(fake_db, issue_state="open")
    fake_update = AsyncMock(return_value={"state": "closed"})
    monkeypatch.setattr("services.github_writeback.update_issue", fake_update)

    await sync_task_status_to_github(fake_db, WORKSPACE, task, "tok", close=True)

    fake_update.assert_awaited_once()
    assert fake_update.await_args.kwargs["state"] == "closed"
    updated = fake_db.table("github_issues").select("*").eq("id", issue["id"]).single().execute().data
    assert updated["state"] == "closed"


@pytest.mark.asyncio
async def test_sync_task_status_to_github_reopen_success(fake_db, monkeypatch):
    from services.github_writeback import sync_task_status_to_github

    issue, task = _seed_linked_issue_and_task(fake_db, issue_state="closed")
    fake_update = AsyncMock(return_value={"state": "open"})
    monkeypatch.setattr("services.github_writeback.update_issue", fake_update)

    await sync_task_status_to_github(fake_db, WORKSPACE, task, "tok", close=False)

    assert fake_update.await_args.kwargs["state"] == "open"
    updated = fake_db.table("github_issues").select("*").eq("id", issue["id"]).single().execute().data
    assert updated["state"] == "open"


@pytest.mark.asyncio
async def test_sync_task_status_to_github_missing_issue_is_noop(fake_db, monkeypatch):
    from services.github_writeback import sync_task_status_to_github

    task = fake_db.table("tasks").insert({
        "workspace_id": "ws-1", "title": "Orphan", "github_issue_id": "nonexistent-id",
    }).execute().data[0]
    fake_update = AsyncMock()
    monkeypatch.setattr("services.github_writeback.update_issue", fake_update)

    await sync_task_status_to_github(fake_db, WORKSPACE, task, "tok", close=True)

    fake_update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("close,expected_kind", [(True, "close_issue"), (False, "reopen_issue")])
async def test_sync_task_status_to_github_failure_queues_outbox(fake_db, monkeypatch, close, expected_kind):
    """A GitHub outage during close/reopen must never raise back to the
    caller -- it queues an outbox retry instead (module docstring contract)."""
    from services.github_writeback import sync_task_status_to_github

    _, task = _seed_linked_issue_and_task(fake_db)
    monkeypatch.setattr(
        "services.github_writeback.update_issue",
        AsyncMock(side_effect=httpx.ConnectTimeout("github down")),
    )

    await sync_task_status_to_github(fake_db, WORKSPACE, task, "tok", close=close)

    outbox = fake_db.table("github_write_outbox").select("*").eq("task_id", task["id"]).execute().data
    assert len(outbox) == 1
    assert outbox[0]["kind"] == expected_kind
    assert outbox[0]["payload"]["issue_number"] == 12


@pytest.mark.asyncio
async def test_update_issue_for_task_failure_queues_outbox(fake_db, monkeypatch):
    issue, task = _seed_linked_issue_and_task(fake_db)
    monkeypatch.setattr(
        "services.github_writeback.update_issue",
        AsyncMock(side_effect=httpx.ConnectTimeout("down")),
    )

    await update_issue_for_task(fake_db, WORKSPACE, task, "tok")

    outbox = fake_db.table("github_write_outbox").select("*").eq("task_id", task["id"]).execute().data
    assert len(outbox) == 1
    assert outbox[0]["kind"] == "update_issue"
    assert outbox[0]["payload"]["issue_number"] == issue["number"]


# --- drain_outbox retry kinds beyond create_issue -----------------------------


def _seed_outbox_row(fake_db, kind, payload):
    fake_db.table("workspaces").insert({
        "id": "ws-1", "name": "Test", "owner_id": "user-1", "state": "active",
        "repo_owner": "acme", "repo_name": "widgets", "webhook_secret": "shh",
    }).execute()
    task = fake_db.table("tasks").insert({"workspace_id": "ws-1", "title": "T"}).execute().data[0]
    row = fake_db.table("github_write_outbox").insert({
        "workspace_id": "ws-1", "task_id": task["id"], "kind": kind,
        "payload": payload, "attempts": 1, "last_error": "boom",
    }).execute().data[0]
    return row


@pytest.mark.asyncio
async def test_retry_one_update_issue_kind_succeeds(fake_db, monkeypatch):
    row = _seed_outbox_row(fake_db, "update_issue", {"issue_number": 3, "title": "T", "body": "d"})
    monkeypatch.setattr("services.github.get_github_token", lambda db, uid: "tok")
    fake_update = AsyncMock(return_value={"title": "T", "body": "d", "state": "open"})
    monkeypatch.setattr("services.github_writeback.update_issue", fake_update)

    await drain_outbox(fake_db)

    fake_update.assert_awaited_once()
    saved = fake_db.table("github_write_outbox").select("*").eq("id", row["id"]).single().execute().data
    assert saved["completed_at"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,expected_state", [("close_issue", "closed"), ("reopen_issue", "open")])
async def test_retry_one_close_and_reopen_issue_kinds(fake_db, monkeypatch, kind, expected_state):
    row = _seed_outbox_row(fake_db, kind, {"issue_number": 4})
    monkeypatch.setattr("services.github.get_github_token", lambda db, uid: "tok")
    fake_update = AsyncMock(return_value={"state": expected_state})
    monkeypatch.setattr("services.github_writeback.update_issue", fake_update)

    await drain_outbox(fake_db)

    assert fake_update.await_args.kwargs["state"] == expected_state
    saved = fake_db.table("github_write_outbox").select("*").eq("id", row["id"]).single().execute().data
    assert saved["completed_at"] is not None
