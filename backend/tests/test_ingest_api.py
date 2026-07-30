"""API tests for the ingest pipeline: typed error surfacing, real usage
logging, cache behavior, and partial-progress persistence."""

import pytest
from google.genai import errors as genai_errors

import routers.ingest as ingest_module
from models.decomposition import (
    ClarifyingQuestionsResult,
    DecompositionEpic,
    DecompositionResult,
    DecompositionTask,
)
from services.ai import GeminiError, GeminiErrorKind
from tests.conftest import USER_ID


@pytest.fixture
def profile(fake_db):
    fake_db.seed("profiles", [{"id": USER_ID, "gemini_api_key": "test-key"}])


def _api_error(code: int) -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"message": "raw sdk secret", "status": "X"}})


def _decomposition() -> DecompositionResult:
    return DecompositionResult(
        summary="s",
        epics=[
            DecompositionEpic(
                title="E1",
                tasks=[DecompositionTask(title="T1", description="d", motivation="m", estimated_days=1)],
            )
        ],
    )


def _no_questions(usage=None):
    async def fake(*args, **kwargs):
        return ClarifyingQuestionsResult(questions=[]), usage or {"tokens_in": 10, "tokens_out": 5}

    return fake


class TestErrorSurfacing:
    def test_invalid_key_returns_400_with_actionable_message(self, client, fake_db, workspace, profile, monkeypatch):
        async def boom(*args, **kwargs):
            raise _api_error(401)

        monkeypatch.setattr(ingest_module, "generate_questions", boom)
        res = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": "PRD"})

        assert res.status_code == 400
        detail = res.json()["detail"]
        assert detail["kind"] == "invalid_key"
        assert "profile settings" in detail["message"]
        assert "raw sdk secret" not in res.text

    def test_rate_limit_returns_429_with_retry_guidance(self, client, fake_db, workspace, profile, monkeypatch):
        async def boom(*args, **kwargs):
            raise _api_error(429)

        monkeypatch.setattr(ingest_module, "generate_questions", boom)
        res = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": "PRD"})

        assert res.status_code == 429
        detail = res.json()["detail"]
        assert detail["kind"] == "quota_exceeded"
        assert detail["retry_after"] == 60

    def test_server_error_returns_502_without_raw_exception(self, client, fake_db, workspace, profile, monkeypatch):
        async def boom(*args, **kwargs):
            raise _api_error(503)

        monkeypatch.setattr(ingest_module, "generate_questions", boom)
        res = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": "PRD"})

        assert res.status_code == 502
        assert res.json()["detail"]["kind"] == "server_error"
        assert "raw sdk secret" not in res.text

    def test_timeout_returns_502(self, client, fake_db, workspace, profile, monkeypatch):
        async def boom(*args, **kwargs):
            raise GeminiError(GeminiErrorKind.TIMEOUT, "The request to Gemini timed out. Please retry.")

        monkeypatch.setattr(ingest_module, "generate_questions", boom)
        res = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": "PRD"})

        assert res.status_code == 502
        assert res.json()["detail"]["kind"] == "timeout"


class TestUsageLogging:
    def test_logs_real_token_counts_and_correct_model(self, client, fake_db, workspace, profile, monkeypatch):
        """Regression: usage rows used hardcoded 500/200 + 20000/8000 counts
        and the decompose call was mislabeled 'gemini-3.1-pro'."""
        monkeypatch.setattr(
            ingest_module, "generate_questions", _no_questions({"tokens_in": 111, "tokens_out": 22})
        )

        async def fake_decompose(*args, **kwargs):
            return _decomposition(), {"tokens_in": 3456, "tokens_out": 789}

        monkeypatch.setattr(ingest_module, "decompose_prd", fake_decompose)

        res = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": "PRD"})
        assert res.status_code == 200

        usage_rows = fake_db.store.rows("ai_usage")
        assert len(usage_rows) == 2
        assert all(r["model"] == "gemini-3.1-flash-lite" for r in usage_rows)
        assert {(r["tokens_in"], r["tokens_out"]) for r in usage_rows} == {(111, 22), (3456, 789)}


class TestWorkspaceScheduleSync:
    def test_decompose_persists_schedule_settings_to_workspace(
        self, client, fake_db, workspace, profile, monkeypatch
    ):
        """Regression: the settings page timeline read schedule_start_date /
        tickets_per_member_per_week / assign_day off the workspace row, but
        ingestion only used them transiently to schedule tasks and never
        wrote them back -- so the fields always showed empty."""
        monkeypatch.setattr(ingest_module, "generate_questions", _no_questions())

        async def fake_decompose(*args, **kwargs):
            return _decomposition(), {"tokens_in": 1, "tokens_out": 1}

        monkeypatch.setattr(ingest_module, "decompose_prd", fake_decompose)

        res = client.post(
            f"/workspaces/{workspace['id']}/ingest",
            json={
                "content": "PRD",
                "context": {
                    "start_date": "2026-08-03",
                    "tickets_per_member_per_week": 2,
                    "assign_day": 1,
                },
            },
        )
        assert res.status_code == 200

        ws = fake_db.table("workspaces").select("*").eq("id", workspace["id"]).single().execute().data
        assert ws["schedule_start_date"] == "2026-08-03"
        assert ws["tickets_per_member_per_week"] == 2
        assert ws["assign_day"] == 1


class TestCaching:
    def test_identical_content_served_from_cache(self, client, fake_db, workspace, profile, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr(ingest_module, "generate_questions", _no_questions())

        async def fake_decompose(*args, **kwargs):
            calls["n"] += 1
            return _decomposition(), {"tokens_in": 1, "tokens_out": 1}

        monkeypatch.setattr(ingest_module, "decompose_prd", fake_decompose)

        first = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": "Same PRD"})
        second = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": "Same PRD"})

        assert first.status_code == second.status_code == 200
        assert first.json()["cached"] is False
        assert second.json()["cached"] is True
        assert calls["n"] == 1

    def test_partial_progress_row_is_not_served_as_cache(self, client, fake_db, workspace, profile, monkeypatch):
        import routers.ingest as im

        fake_db.seed("ingestions", [{
            "workspace_id": workspace["id"],
            "content_hash": im._content_hash("PRD"),
            "raw_content": "PRD",
            "decomposition": {"partial": True, "summary": "s", "epics": []},
        }])
        monkeypatch.setattr(
            ingest_module,
            "generate_questions",
            _no_questions(),
        )

        async def fake_decompose(*args, **kwargs):
            return _decomposition(), {"tokens_in": 1, "tokens_out": 1}

        monkeypatch.setattr(ingest_module, "decompose_prd", fake_decompose)

        res = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": "PRD"})
        assert res.status_code == 200
        assert res.json()["cached"] is False  # partial row must not short-circuit


class TestPartialProgress:
    def test_failure_mid_decomposition_persists_partial_and_reports_progress(
        self, client, fake_db, workspace, profile, monkeypatch
    ):
        """Regression: failing on epic 2 of 3 used to discard epic 1 entirely."""
        monkeypatch.setattr(ingest_module, "generate_questions", _no_questions())

        async def fake_decompose(content, ctx, answers, key, on_epic_done=None):
            partial = DecompositionResult(
                summary="s",
                epics=[DecompositionEpic(title="E1", tasks=[])],
            )
            if on_epic_done:
                on_epic_done(partial, 3)
            raise GeminiError(GeminiErrorKind.SERVER_ERROR, "Gemini is temporarily unavailable. Please retry.")

        monkeypatch.setattr(ingest_module, "decompose_prd", fake_decompose)

        res = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": "PRD"})

        assert res.status_code == 502
        detail = res.json()["detail"]
        assert detail["partial_epics_completed"] == 1
        assert detail["total_epics"] == 3

        rows = fake_db.store.rows("ingestions")
        assert len(rows) == 1
        assert rows[0]["decomposition"]["partial"] is True
        assert [e["title"] for e in rows[0]["decomposition"]["epics"]] == ["E1"]


class TestPrdLengthLimit:
    def test_oversized_prd_returns_400(self, client, fake_db, workspace, profile):
        huge = "x" * (ingest_module.MAX_PRD_CHARS + 1)

        res = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": huge})

        assert res.status_code == 400
        assert "too large" in res.json()["detail"]

    def test_prd_at_limit_is_accepted(self, client, fake_db, workspace, profile, monkeypatch):
        monkeypatch.setattr(ingest_module, "generate_questions", _no_questions())

        async def fake_decompose(*args, **kwargs):
            return _decomposition(), {"tokens_in": 1, "tokens_out": 1}

        monkeypatch.setattr(ingest_module, "decompose_prd", fake_decompose)
        content = "x" * ingest_module.MAX_PRD_CHARS

        res = client.post(f"/workspaces/{workspace['id']}/ingest", json={"content": content})

        assert res.status_code == 200

    def test_answer_endpoint_also_enforces_limit(self, client, fake_db, workspace, profile):
        huge = "x" * (ingest_module.MAX_PRD_CHARS + 1)

        res = client.post(
            f"/workspaces/{workspace['id']}/ingest/answer",
            json={"content": huge, "answers": {}},
        )

        assert res.status_code == 400
        assert "too large" in res.json()["detail"]
