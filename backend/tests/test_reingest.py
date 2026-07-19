"""Tests for re-ingestion reliability: content-hash caching, typed error
surfacing, approve idempotency, and task-embedding population on approval."""

import pytest
from google.genai import errors as genai_errors

import routers.projects as projects_module
from models.decomposition import DecompositionEpic, DecompositionResult, DecompositionTask
from tests.conftest import USER_ID


@pytest.fixture
def profile(fake_db):
    fake_db.seed("profiles", [{"id": USER_ID, "gemini_api_key": "test-key"}])


def _decomposition(titles=("New task one",)) -> DecompositionResult:
    return DecompositionResult(
        summary="s",
        epics=[
            DecompositionEpic(
                title="E1",
                tasks=[
                    DecompositionTask(title=t, description="d", motivation="m", estimated_days=1)
                    for t in titles
                ],
            )
        ],
    )


class TestReingestCache:
    def test_identical_reingest_does_not_recall_gemini(self, client, fake_db, workspace, profile, monkeypatch):
        """Regression: reingest_prd had no content-hash cache check at all."""
        calls = {"n": 0}

        async def fake_decompose(*args, **kwargs):
            calls["n"] += 1
            return _decomposition(), {"tokens_in": 1, "tokens_out": 1}

        monkeypatch.setattr(projects_module, "decompose_prd", fake_decompose)

        first = client.post(f"/workspaces/{workspace['id']}/reingest", json={"content": "Updated PRD"})
        second = client.post(f"/workspaces/{workspace['id']}/reingest", json={"content": "Updated PRD"})

        assert first.status_code == second.status_code == 200
        assert calls["n"] == 1  # second call served from the ingestions cache
        assert first.json() == second.json()

    def test_reingest_uses_preexisting_ingest_cache_row(self, client, fake_db, workspace, profile, monkeypatch):
        from routers.ingest import _content_hash

        fake_db.seed("ingestions", [{
            "workspace_id": workspace["id"],
            "content_hash": _content_hash("Cached PRD"),
            "raw_content": "Cached PRD",
            "decomposition": _decomposition().model_dump(),
        }])

        async def must_not_be_called(*args, **kwargs):
            raise AssertionError("decompose_prd should not be called on a cache hit")

        monkeypatch.setattr(projects_module, "decompose_prd", must_not_be_called)

        res = client.post(f"/workspaces/{workspace['id']}/reingest", json={"content": "Cached PRD"})
        assert res.status_code == 200
        assert [a["new_task"]["title"] for a in res.json()["added"]] == ["New task one"]

    def test_reingest_ai_failure_returns_typed_error(self, client, fake_db, workspace, profile, monkeypatch):
        async def boom(*args, **kwargs):
            raise genai_errors.APIError(401, {"error": {"message": "raw sdk secret", "status": "X"}})

        monkeypatch.setattr(projects_module, "decompose_prd", boom)

        res = client.post(f"/workspaces/{workspace['id']}/reingest", json={"content": "PRD"})
        assert res.status_code == 400
        assert res.json()["detail"]["kind"] == "invalid_key"
        assert "raw sdk secret" not in res.text


class TestApproveReingestIdempotency:
    def _payload(self, **overrides):
        payload = {
            "added": [{"title": "Brand new task", "description": "d"}],
            "removed_task_ids": [],
            "modified": [],
        }
        payload.update(overrides)
        return payload

    def test_double_submit_with_idempotency_key_applies_once(self, client, fake_db, workspace):
        payload = self._payload(idempotency_key="review-session-1")

        first = client.post(f"/workspaces/{workspace['id']}/reingest/approve", json=payload)
        second = client.post(f"/workspaces/{workspace['id']}/reingest/approve", json=payload)

        assert first.status_code == second.status_code == 200
        assert first.json()["status"] == "applied"
        assert second.json()["status"] == "already_applied"

        tasks = fake_db.store.rows("tasks")
        assert len([t for t in tasks if t["title"] == "Brand new task"]) == 1

    def test_double_submit_without_key_still_deduplicates_added_tasks(self, client, fake_db, workspace):
        """Regression: the added-tasks path unconditionally inserted rows,
        so a double click created duplicate tasks."""
        payload = self._payload()

        client.post(f"/workspaces/{workspace['id']}/reingest/approve", json=payload)
        client.post(f"/workspaces/{workspace['id']}/reingest/approve", json=payload)

        tasks = fake_db.store.rows("tasks")
        assert len([t for t in tasks if t["title"] == "Brand new task"]) == 1


class TestApprovalEmbeddings:
    def _seed_ingestion(self, fake_db, workspace):
        fake_db.seed("ingestions", [{
            "workspace_id": workspace["id"],
            "content_hash": "h",
            "raw_content": "PRD",
            "decomposition": _decomposition(titles=("Task A", "Task B")).model_dump(),
            "created_at": "2026-01-01T00:00:00Z",
        }])

    def test_approve_plan_populates_task_embeddings(self, client, fake_db, workspace, profile, monkeypatch):
        """Regression: tasks.embedding was never written, silently disabling
        semantic matching for every task."""
        self._seed_ingestion(fake_db, workspace)

        async def fake_embeddings(texts, key):
            assert key == "test-key"
            return [[0.1] * 3 for _ in texts]

        monkeypatch.setattr(projects_module, "generate_embeddings", fake_embeddings)

        res = client.post(f"/workspaces/{workspace['id']}/plan/approve")
        assert res.status_code == 200

        tasks = fake_db.store.rows("tasks")
        assert len(tasks) == 2
        assert all(t.get("embedding") == [0.1, 0.1, 0.1] for t in tasks)

    def test_embedding_failure_does_not_fail_approval(self, client, fake_db, workspace, profile, monkeypatch):
        self._seed_ingestion(fake_db, workspace)

        async def boom(texts, key):
            raise genai_errors.APIError(429, {"error": {"message": "quota", "status": "X"}})

        monkeypatch.setattr(projects_module, "generate_embeddings", boom)

        res = client.post(f"/workspaces/{workspace['id']}/plan/approve")
        assert res.status_code == 200

        tasks = fake_db.store.rows("tasks")
        assert len(tasks) == 2
        assert all(t.get("embedding") is None for t in tasks)

    def test_missing_gemini_key_does_not_fail_approval(self, client, fake_db, workspace, monkeypatch):
        self._seed_ingestion(fake_db, workspace)

        async def must_not_be_called(*args, **kwargs):
            raise AssertionError("no key -> embeddings must be skipped entirely")

        monkeypatch.setattr(projects_module, "generate_embeddings", must_not_be_called)

        res = client.post(f"/workspaces/{workspace['id']}/plan/approve")
        assert res.status_code == 200
        assert len(fake_db.store.rows("tasks")) == 2


class TestReingestPrdLengthLimit:
    def test_oversized_reingest_prd_returns_400(self, client, fake_db, workspace, profile):
        from routers.ingest import MAX_PRD_CHARS

        huge = "x" * (MAX_PRD_CHARS + 1)

        res = client.post(f"/workspaces/{workspace['id']}/reingest", json={"content": huge})

        assert res.status_code == 400
        assert "too large" in res.json()["detail"]
