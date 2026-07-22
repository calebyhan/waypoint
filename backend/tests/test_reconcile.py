"""Tests for services/reconcile.py: the 15-minute GitHub polling safety net.

GitHub HTTP traffic is faked with httpx.MockTransport so the real request
building (URLs, params, headers) still runs.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import services.reconcile as reconcile_module
from core.crypto import encrypt
from services.reconcile import (
    _reconcile_workspace,
    _upsert_issue,
    reconcile_all_workspaces,
)

OWNER_ID = "11111111-1111-1111-1111-111111111111"

WORKSPACE = {
    "id": "ws-1",
    "owner_id": OWNER_ID,
    "state": "active",
    "repo_owner": "acme",
    "repo_name": "widgets",
}


def _iso_minutes_ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _mock_github(monkeypatch, issues=None, pulls=None, issues_status=200, pulls_status=200):
    """Route GitHub API calls through an in-memory transport."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/issues"):
            return httpx.Response(issues_status, json=issues or [])
        if path.endswith("/pulls"):
            return httpx.Response(pulls_status, json=pulls or [])
        raise AssertionError(f"unexpected GitHub call: {path}")

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        reconcile_module,
        "httpx",
        SimpleNamespace(AsyncClient=lambda **kw: httpx.AsyncClient(transport=transport, **kw)),
    )


@pytest.mark.asyncio
async def test_reconcile_all_workspaces_skips_workspaces_without_repo(fake_db, monkeypatch):
    fake_db.seed("workspaces", [
        {"id": "ws-no-repo", "state": "active", "repo_owner": None, "repo_name": None, "owner_id": OWNER_ID},
        {**WORKSPACE},
    ])
    spy = AsyncMock()
    monkeypatch.setattr(reconcile_module, "_reconcile_workspace", spy)

    await reconcile_all_workspaces(fake_db)

    assert spy.await_count == 1
    assert spy.await_args.args[1]["id"] == "ws-1"


@pytest.mark.asyncio
async def test_reconcile_all_workspaces_isolates_per_workspace_failures(fake_db, monkeypatch):
    fake_db.seed("workspaces", [
        {**WORKSPACE, "id": "ws-boom"},
        {**WORKSPACE, "id": "ws-ok"},
    ])
    reconciled = []

    async def fake_reconcile(db, workspace):
        if workspace["id"] == "ws-boom":
            raise RuntimeError("simulated failure")
        reconciled.append(workspace["id"])

    monkeypatch.setattr(reconcile_module, "_reconcile_workspace", fake_reconcile)

    await reconcile_all_workspaces(fake_db)  # must not raise

    assert reconciled == ["ws-ok"]


@pytest.mark.asyncio
async def test_reconcile_workspace_returns_early_with_no_github_token(fake_db, monkeypatch):
    fake_db.seed("profiles", [{"id": OWNER_ID, "gemini_api_key": None}])
    monkeypatch.setattr(reconcile_module, "get_github_token", lambda db, uid: None)

    def explode(**kw):
        raise AssertionError("httpx must not be called without a token")

    monkeypatch.setattr(reconcile_module, "httpx", SimpleNamespace(AsyncClient=explode))

    await _reconcile_workspace(fake_db, WORKSPACE)  # no exception, no HTTP


@pytest.mark.asyncio
async def test_gemini_key_is_decrypted_before_matching(fake_db, monkeypatch):
    """Regression: reconcile read profiles.gemini_api_key raw even though keys
    are Fernet-encrypted at rest, so semantic matching got ciphertext."""
    fake_db.seed("profiles", [{"id": OWNER_ID, "gemini_api_key": encrypt("AIzaSyRealKey123")}])
    monkeypatch.setattr(reconcile_module, "get_github_token", lambda db, uid: "tok")
    _mock_github(monkeypatch, issues=[
        {"id": 1, "number": 1, "title": "Bug", "state": "open", "updated_at": _iso_minutes_ago(1)},
    ])
    handle = AsyncMock()
    monkeypatch.setattr(reconcile_module, "handle_issue_change", handle)

    await _reconcile_workspace(fake_db, WORKSPACE)

    assert handle.await_count == 1
    assert handle.await_args.args[4] == "AIzaSyRealKey123"


@pytest.mark.asyncio
async def test_legacy_plaintext_gemini_key_passes_through(fake_db, monkeypatch):
    fake_db.seed("profiles", [{"id": OWNER_ID, "gemini_api_key": "legacy-plain"}])
    monkeypatch.setattr(reconcile_module, "get_github_token", lambda db, uid: "tok")
    _mock_github(monkeypatch, issues=[
        {"id": 1, "number": 1, "title": "Bug", "state": "open", "updated_at": _iso_minutes_ago(1)},
    ])
    handle = AsyncMock()
    monkeypatch.setattr(reconcile_module, "handle_issue_change", handle)

    await _reconcile_workspace(fake_db, WORKSPACE)

    assert handle.await_args.args[4] == "legacy-plain"


@pytest.mark.asyncio
async def test_reconcile_workspace_skips_pull_requests_disguised_as_issues(fake_db, monkeypatch):
    fake_db.seed("profiles", [{"id": OWNER_ID, "gemini_api_key": None}])
    monkeypatch.setattr(reconcile_module, "get_github_token", lambda db, uid: "tok")
    _mock_github(monkeypatch, issues=[
        {"id": 1, "number": 1, "title": "Real issue", "state": "open"},
        {"id": 2, "number": 2, "title": "PR in disguise", "state": "open", "pull_request": {"url": "x"}},
    ])
    upsert_spy = AsyncMock()
    monkeypatch.setattr(reconcile_module, "_upsert_issue", upsert_spy)

    await _reconcile_workspace(fake_db, WORKSPACE)

    assert upsert_spy.await_count == 1
    assert upsert_spy.await_args.args[2]["id"] == 1


@pytest.mark.asyncio
async def test_reconcile_workspace_ignores_non_200_issue_response(fake_db, monkeypatch):
    fake_db.seed("profiles", [{"id": OWNER_ID, "gemini_api_key": None}])
    monkeypatch.setattr(reconcile_module, "get_github_token", lambda db, uid: "tok")
    _mock_github(monkeypatch, issues_status=403, pulls_status=403)
    upsert_issue_spy = AsyncMock()
    upsert_pr_spy = AsyncMock()
    monkeypatch.setattr(reconcile_module, "_upsert_issue", upsert_issue_spy)
    monkeypatch.setattr(reconcile_module, "_upsert_pr", upsert_pr_spy)

    await _reconcile_workspace(fake_db, WORKSPACE)  # rate-limited: no raise

    assert upsert_issue_spy.await_count == 0
    assert upsert_pr_spy.await_count == 0


@pytest.mark.asyncio
async def test_reconcile_workspace_filters_prs_outside_window(fake_db, monkeypatch):
    fake_db.seed("profiles", [{"id": OWNER_ID, "gemini_api_key": None}])
    monkeypatch.setattr(reconcile_module, "get_github_token", lambda db, uid: "tok")
    _mock_github(monkeypatch, pulls=[
        {"id": 10, "number": 5, "title": "Fresh", "state": "open", "updated_at": _iso_minutes_ago(5)},
        {"id": 11, "number": 6, "title": "Stale", "state": "open", "updated_at": _iso_minutes_ago(45)},
    ])
    pr_spy = AsyncMock()
    monkeypatch.setattr(reconcile_module, "_upsert_pr", pr_spy)

    await _reconcile_workspace(fake_db, WORKSPACE)

    assert pr_spy.await_count == 1
    assert pr_spy.await_args.args[2]["id"] == 10


@pytest.mark.asyncio
async def test_upsert_issue_reports_opened_for_new_and_updated_for_existing(fake_db, monkeypatch):
    handle = AsyncMock()
    monkeypatch.setattr(reconcile_module, "handle_issue_change", handle)
    issue = {"id": 7, "number": 7, "title": "Bug", "state": "open"}

    await _upsert_issue(fake_db, WORKSPACE, issue, None)
    await _upsert_issue(fake_db, WORKSPACE, issue, None)

    actions = [call.args[3] for call in handle.await_args_list]
    is_new_flags = [call.kwargs["is_new"] for call in handle.await_args_list]
    assert actions == ["opened", "updated"]
    assert is_new_flags == [True, False]
    rows = fake_db.table("github_issues").select("*").eq("workspace_id", "ws-1").execute().data
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_concurrent_reconcile_and_webhook_for_same_issue_dedupe_proposal(fake_db):
    """Reconcile poller and webhook handler both discovering the same issue
    must converge on a single match proposal (upsert on_conflict dedupe)."""
    from services.github_sync import handle_issue_change, upsert_issue

    fake_db.seed("tasks", [{"id": "t-1", "workspace_id": "ws-1", "title": "Add JWT refresh logic"}])
    issue = {"id": 42, "number": 42, "title": "Add JWT refresh logic", "state": "open"}

    # Reconcile path (real handlers, no Gemini key -> fuzzy matching only).
    await _upsert_issue(fake_db, WORKSPACE, issue, None)
    # Webhook path for the same delivery arriving right after.
    saved = await upsert_issue(fake_db, "ws-1", issue)
    await handle_issue_change(fake_db, WORKSPACE, saved, "opened", None, is_new=False)

    proposals = fake_db.table("match_proposals").select("*").eq("workspace_id", "ws-1").execute().data
    assert len(proposals) == 1


@pytest.mark.asyncio
async def test_reconcile_workspace_sends_since_param_and_auth_header(fake_db, monkeypatch):
    fake_db.seed("profiles", [{"id": OWNER_ID, "gemini_api_key": None}])
    monkeypatch.setattr(reconcile_module, "get_github_token", lambda db, uid: "tok-abc")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        reconcile_module,
        "httpx",
        SimpleNamespace(AsyncClient=lambda **kw: httpx.AsyncClient(transport=transport, **kw)),
    )

    await _reconcile_workspace(fake_db, WORKSPACE)

    assert len(seen) == 2
    issues_req = next(r for r in seen if r.url.path.endswith("/issues"))
    assert issues_req.headers["Authorization"] == "Bearer tok-abc"
    assert "since=" in str(issues_req.url.query)
