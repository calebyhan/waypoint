"""Unit tests for services/github.py REST helpers with httpx.MockTransport,
so the real URL/param/header/payload construction is exercised without the
network."""

import json
from types import SimpleNamespace

import httpx
import pytest

import services.github as github_module
from services.github import create_issue, list_repos, update_issue, validate_repo


def _mock_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        github_module,
        "httpx",
        SimpleNamespace(AsyncClient=lambda **kw: httpx.AsyncClient(transport=transport, **kw)),
    )


@pytest.mark.asyncio
async def test_validate_repo_returns_true_on_200(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/acme/widgets"
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"full_name": "acme/widgets"})

    _mock_transport(monkeypatch, handler)

    assert await validate_repo("acme", "widgets", "tok") is True


@pytest.mark.asyncio
async def test_validate_repo_returns_false_on_404(monkeypatch):
    _mock_transport(monkeypatch, lambda request: httpx.Response(404, json={"message": "Not Found"}))

    assert await validate_repo("acme", "gone", "tok") is False


@pytest.mark.asyncio
async def test_create_issue_posts_title_and_body(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 1, "number": 10, "title": "T", "state": "open"})

    _mock_transport(monkeypatch, handler)

    issue = await create_issue("tok", "acme", "widgets", "T", "the body")

    assert seen["path"] == "/repos/acme/widgets/issues"
    assert seen["payload"] == {"title": "T", "body": "the body"}
    assert issue["number"] == 10


@pytest.mark.asyncio
async def test_create_issue_raises_on_error_status(monkeypatch):
    _mock_transport(monkeypatch, lambda request: httpx.Response(502, json={"message": "bad gateway"}))

    with pytest.raises(httpx.HTTPStatusError):
        await create_issue("tok", "acme", "widgets", "T", None)


@pytest.mark.asyncio
async def test_update_issue_only_sends_provided_fields(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"state": "closed"})

    _mock_transport(monkeypatch, handler)

    result = await update_issue("tok", "acme", "widgets", 12, state="closed")

    assert seen["method"] == "PATCH"
    assert seen["path"] == "/repos/acme/widgets/issues/12"
    assert seen["payload"] == {"state": "closed"}  # no title/body keys leaked
    assert result["state"] == "closed"


@pytest.mark.asyncio
async def test_list_repos_maps_fields_and_stops_on_short_page(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=[
            {"full_name": "acme/widgets", "owner": {"login": "acme"}, "name": "widgets"},
            {"full_name": "acme/gears", "owner": {"login": "acme"}, "name": "gears"},
        ])

    _mock_transport(monkeypatch, handler)

    repos = await list_repos("tok")

    assert len(calls) == 1  # short page (<100) ends pagination
    assert repos == [
        {"full_name": "acme/widgets", "owner": "acme", "name": "widgets"},
        {"full_name": "acme/gears", "owner": "acme", "name": "gears"},
    ]


@pytest.mark.asyncio
async def test_list_repos_paginates_past_full_pages(monkeypatch):
    pages = {
        "1": [{"full_name": f"acme/r{i}", "owner": {"login": "acme"}, "name": f"r{i}"} for i in range(100)],
        "2": [{"full_name": "acme/last", "owner": {"login": "acme"}, "name": "last"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[request.url.params["page"]])

    _mock_transport(monkeypatch, handler)

    repos = await list_repos("tok")

    assert len(repos) == 101
    assert repos[-1]["name"] == "last"


@pytest.mark.asyncio
async def test_list_repos_raises_on_auth_failure(monkeypatch):
    _mock_transport(monkeypatch, lambda request: httpx.Response(401, json={"message": "Bad credentials"}))

    with pytest.raises(httpx.HTTPStatusError):
        await list_repos("expired-tok")
