"""End-to-end tests for POST /webhooks/github: replay protection and Gemini key decryption."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock

from core.crypto import encrypt
from tests.conftest import USER_ID

SECRET = "shh"


def _sign(payload: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _issue_payload():
    return {
        "action": "opened",
        "repository": {"owner": {"login": "acme"}, "name": "widgets"},
        "issue": {"id": 101, "number": 1, "title": "Bug", "state": "open"},
    }


def _post_webhook(client, payload: dict, delivery_id: str, secret: str = SECRET):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(body, secret),
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": delivery_id,
        },
    )


def _setup(fake_db, monkeypatch, gemini_api_key=None):
    fake_db.seed("workspaces", [{
        "id": "ws-1", "name": "WS", "owner_id": USER_ID, "state": "active",
        "repo_owner": "acme", "repo_name": "widgets", "webhook_secret": SECRET,
    }])
    fake_db.seed("profiles", [{"id": USER_ID, "github_username": "alice", "gemini_api_key": gemini_api_key}])
    # The webhook router calls get_supabase() directly (no Depends), so patch it.
    monkeypatch.setattr("routers.webhooks.get_supabase", lambda: fake_db)
    upsert = AsyncMock(return_value={"id": "gh-issue-1"})
    handle = AsyncMock()
    monkeypatch.setattr("routers.webhooks.upsert_issue", upsert)
    monkeypatch.setattr("routers.webhooks.handle_issue_change", handle)
    return upsert, handle


def test_valid_delivery_is_processed_once(client, fake_db, monkeypatch):
    upsert, handle = _setup(fake_db, monkeypatch)

    res = _post_webhook(client, _issue_payload(), delivery_id="d-1")

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert upsert.await_count == 1
    assert handle.await_count == 1


def test_replayed_delivery_is_ignored(client, fake_db, monkeypatch):
    upsert, handle = _setup(fake_db, monkeypatch)

    first = _post_webhook(client, _issue_payload(), delivery_id="d-dup")
    second = _post_webhook(client, _issue_payload(), delivery_id="d-dup")

    assert first.json() == {"status": "ok"}
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate"}
    # Handlers ran only for the first delivery.
    assert upsert.await_count == 1
    assert handle.await_count == 1


def test_distinct_deliveries_both_process(client, fake_db, monkeypatch):
    upsert, handle = _setup(fake_db, monkeypatch)

    _post_webhook(client, _issue_payload(), delivery_id="d-a")
    _post_webhook(client, _issue_payload(), delivery_id="d-b")

    assert upsert.await_count == 2
    assert handle.await_count == 2


def test_invalid_signature_rejected_and_not_recorded(client, fake_db, monkeypatch):
    upsert, handle = _setup(fake_db, monkeypatch)

    res = _post_webhook(client, _issue_payload(), delivery_id="d-bad", secret="wrong")

    assert res.status_code == 401
    assert upsert.await_count == 0
    # A forged delivery must not burn the delivery ID for the genuine one.
    recorded = fake_db.table("github_webhook_deliveries").select("*").execute().data
    assert recorded == []


def test_gemini_key_is_decrypted_for_matching(client, fake_db, monkeypatch):
    _, handle = _setup(fake_db, monkeypatch, gemini_api_key=encrypt("AIzaSyPlainKey9999"))

    _post_webhook(client, _issue_payload(), delivery_id="d-key")

    assert handle.await_count == 1
    gemini_key_arg = handle.await_args.args[4]
    assert gemini_key_arg == "AIzaSyPlainKey9999"


def test_legacy_plaintext_gemini_key_still_works(client, fake_db, monkeypatch):
    _, handle = _setup(fake_db, monkeypatch, gemini_api_key="legacy-plain-key")

    _post_webhook(client, _issue_payload(), delivery_id="d-legacy")

    gemini_key_arg = handle.await_args.args[4]
    assert gemini_key_arg == "legacy-plain-key"


# --- Route-level behavior beyond replay protection ----------------------------


def _seed_workspace_only(fake_db, monkeypatch):
    """Like _setup but leaves the real upsert/handle logic in place."""
    fake_db.seed("workspaces", [{
        "id": "ws-1", "name": "WS", "owner_id": USER_ID, "state": "active",
        "repo_owner": "acme", "repo_name": "widgets", "webhook_secret": SECRET,
    }])
    fake_db.seed("profiles", [{"id": USER_ID, "github_username": "alice", "gemini_api_key": None}])
    monkeypatch.setattr("routers.webhooks.get_supabase", lambda: fake_db)


def _post_event(client, payload: dict, event: str, delivery_id: str, secret: str = SECRET):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(body, secret),
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery_id,
        },
    )


def test_webhook_missing_repository_info_returns_400(client, fake_db, monkeypatch):
    _seed_workspace_only(fake_db, monkeypatch)

    res = _post_event(client, {"action": "opened"}, "issues", "d-norepo")

    assert res.status_code == 400


def test_webhook_unknown_repo_returns_404(client, fake_db, monkeypatch):
    _seed_workspace_only(fake_db, monkeypatch)
    payload = {
        "action": "opened",
        "repository": {"owner": {"login": "someone"}, "name": "else"},
        "issue": {"id": 1, "number": 1, "title": "x", "state": "open"},
    }

    res = _post_event(client, payload, "issues", "d-unknown")

    assert res.status_code == 404


def test_webhook_missing_signature_header_returns_401(client, fake_db, monkeypatch):
    _seed_workspace_only(fake_db, monkeypatch)
    body = json.dumps(_issue_payload()).encode()

    res = client.post(
        "/webhooks/github",
        content=body,
        headers={"Content-Type": "application/json", "X-GitHub-Event": "issues"},
    )

    assert res.status_code == 401


def test_webhook_issue_opened_creates_row_end_to_end(client, fake_db, monkeypatch):
    """No handler mocking: the payload flows through upsert_issue and
    handle_issue_change (fuzzy matching, no Gemini key) against the fake DB."""
    _seed_workspace_only(fake_db, monkeypatch)
    fake_db.seed("tasks", [{"id": "t-1", "workspace_id": "ws-1", "title": "Bug", "status": "open"}])

    res = _post_event(client, _issue_payload(), "issues", "d-e2e-issue")

    assert res.status_code == 200
    issues = fake_db.table("github_issues").select("*").eq("workspace_id", "ws-1").execute().data
    assert len(issues) == 1
    assert issues[0]["number"] == 1
    # Fuzzy title match ("Bug" == "Bug") produced a proposal.
    proposals = fake_db.table("match_proposals").select("*").eq("workspace_id", "ws-1").execute().data
    assert len(proposals) == 1
    assert proposals[0]["task_id"] == "t-1"


def test_webhook_pull_request_opened_creates_row_end_to_end(client, fake_db, monkeypatch):
    _seed_workspace_only(fake_db, monkeypatch)
    payload = {
        "action": "opened",
        "repository": {"owner": {"login": "acme"}, "name": "widgets"},
        "pull_request": {"id": 500, "number": 9, "title": "Fix things", "state": "open", "merged_at": None},
    }

    res = _post_event(client, payload, "pull_request", "d-e2e-pr")

    assert res.status_code == 200
    prs = fake_db.table("github_prs").select("*").eq("workspace_id", "ws-1").execute().data
    assert len(prs) == 1
    assert prs[0]["number"] == 9
    assert prs[0]["merged"] is False


def test_webhook_unhandled_event_type_returns_200_and_does_nothing(client, fake_db, monkeypatch):
    _seed_workspace_only(fake_db, monkeypatch)
    payload = {
        "action": "created",
        "repository": {"owner": {"login": "acme"}, "name": "widgets"},
    }

    res = _post_event(client, payload, "star", "d-star")

    assert res.status_code == 200
    assert fake_db.table("github_issues").select("*").execute().data == []
    assert fake_db.table("github_prs").select("*").execute().data == []
