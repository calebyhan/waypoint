"""Unit tests for the Gemini reliability layer in services/ai.py:
error classification, retry/backoff behavior, and decompose_prd's
partial-progress callback + real usage summation."""

import json

import pytest
from google.genai import errors as genai_errors

import services.ai as ai
from core.config import settings
from models.decomposition import (
    ClarifyingQuestionsResult,
    DecompositionTask,
    EpicSkeleton,
    PlanSkeleton,
)
from services.ai import (
    GeminiError,
    GeminiErrorKind,
    _with_retry,
    classify_exception,
    decompose_prd,
)


def _api_error(code: int) -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"message": "secret sdk detail", "status": "X"}})


def _validation_error():
    try:
        ClarifyingQuestionsResult(questions="not-a-list")
    except Exception as e:
        return e


class TestClassifyException:
    @pytest.mark.parametrize("code", [401, 403])
    def test_auth_errors_map_to_invalid_key(self, code):
        err = classify_exception(_api_error(code))
        assert err.kind == GeminiErrorKind.INVALID_KEY
        assert "profile settings" in err.message

    def test_429_maps_to_quota_exceeded_with_retry_after(self):
        err = classify_exception(_api_error(429))
        assert err.kind == GeminiErrorKind.QUOTA_EXCEEDED
        assert err.retry_after == 60

    @pytest.mark.parametrize("code", [500, 503])
    def test_5xx_maps_to_server_error(self, code):
        assert classify_exception(_api_error(code)).kind == GeminiErrorKind.SERVER_ERROR

    def test_timeout_maps_to_timeout(self):
        assert classify_exception(TimeoutError()).kind == GeminiErrorKind.TIMEOUT

    def test_httpx_timeout_maps_to_timeout(self):
        import httpx

        assert classify_exception(httpx.ReadTimeout("t")).kind == GeminiErrorKind.TIMEOUT

    def test_json_decode_error_maps_to_bad_output(self):
        try:
            json.loads("{nope")
        except json.JSONDecodeError as e:
            assert classify_exception(e).kind == GeminiErrorKind.BAD_OUTPUT

    def test_pydantic_validation_error_maps_to_bad_output(self):
        assert classify_exception(_validation_error()).kind == GeminiErrorKind.BAD_OUTPUT

    def test_unknown_error_never_leaks_raw_text(self):
        err = classify_exception(ValueError("raw internal detail with key AIza123"))
        assert err.kind == GeminiErrorKind.UNKNOWN
        assert "AIza123" not in err.message

    def test_api_error_messages_never_include_sdk_detail(self):
        for code in (401, 429, 503):
            assert "secret sdk detail" not in classify_exception(_api_error(code)).message

    def test_gemini_error_passes_through(self):
        original = GeminiError(GeminiErrorKind.TIMEOUT, "m")
        assert classify_exception(original) is original


@pytest.fixture
def fast_retries(monkeypatch):
    monkeypatch.setattr(settings, "gemini_retry_attempts", 3)
    monkeypatch.setattr(settings, "gemini_retry_wait_min", 0.001)
    monkeypatch.setattr(settings, "gemini_retry_wait_max", 0.002)


class TestRetry:
    async def test_retries_on_server_error_then_succeeds(self, fast_retries):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise _api_error(503)
            return "ok"

        assert await _with_retry(flaky) == "ok"
        assert calls["n"] == 3

    async def test_retries_on_429(self, fast_retries):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise _api_error(429)
            return "ok"

        assert await _with_retry(flaky) == "ok"
        assert calls["n"] == 2

    async def test_no_retry_on_invalid_key(self, fast_retries):
        calls = {"n": 0}

        async def bad_key():
            calls["n"] += 1
            raise _api_error(401)

        with pytest.raises(GeminiError) as exc_info:
            await _with_retry(bad_key)
        assert exc_info.value.kind == GeminiErrorKind.INVALID_KEY
        assert calls["n"] == 1

    async def test_no_retry_on_bad_output(self, fast_retries):
        calls = {"n": 0}

        async def bad_json():
            calls["n"] += 1
            json.loads("{nope")

        with pytest.raises(GeminiError) as exc_info:
            await _with_retry(bad_json)
        assert exc_info.value.kind == GeminiErrorKind.BAD_OUTPUT
        assert calls["n"] == 1

    async def test_exhausted_retries_raise_classified_error(self, fast_retries):
        async def always_down():
            raise _api_error(503)

        with pytest.raises(GeminiError) as exc_info:
            await _with_retry(always_down)
        assert exc_info.value.kind == GeminiErrorKind.SERVER_ERROR


def _task(title: str) -> DecompositionTask:
    return DecompositionTask(title=title, description="d", motivation="m", estimated_days=1)


class TestDecomposePrd:
    async def test_sums_real_usage_across_calls(self, monkeypatch):
        skeleton = PlanSkeleton(
            summary="s",
            epics=[EpicSkeleton(title="E1", scope="a"), EpicSkeleton(title="E2", scope="b")],
        )

        async def fake_skeleton(*args, **kwargs):
            return skeleton, {"tokens_in": 100, "tokens_out": 50}

        async def fake_epic_tasks(content, ctx, answers, epic, all_epics, prior, client):
            return [_task(f"{epic.title} task")], {"tokens_in": 10, "tokens_out": 5}

        monkeypatch.setattr(ai, "_generate_skeleton", fake_skeleton)
        monkeypatch.setattr(ai, "_generate_epic_tasks", fake_epic_tasks)

        result, usage = await decompose_prd("prd", None, None, "key")
        assert usage == {"tokens_in": 120, "tokens_out": 60}
        assert [e.title for e in result.epics] == ["E1", "E2"]

    async def test_partial_progress_callback_fires_before_failure(self, monkeypatch):
        """Regression: a failure on epic 2 must not lose epic 1's output --
        the on_epic_done callback lets the caller persist it first."""
        skeleton = PlanSkeleton(
            summary="s",
            epics=[
                EpicSkeleton(title="E1", scope="a"),
                EpicSkeleton(title="E2", scope="b"),
                EpicSkeleton(title="E3", scope="c"),
            ],
        )

        async def fake_skeleton(*args, **kwargs):
            return skeleton, {"tokens_in": 0, "tokens_out": 0}

        async def fake_epic_tasks(content, ctx, answers, epic, all_epics, prior, client):
            if epic.title == "E2":
                raise GeminiError(GeminiErrorKind.SERVER_ERROR, "down")
            return [_task(f"{epic.title} task")], {"tokens_in": 0, "tokens_out": 0}

        monkeypatch.setattr(ai, "_generate_skeleton", fake_skeleton)
        monkeypatch.setattr(ai, "_generate_epic_tasks", fake_epic_tasks)

        seen: list[tuple[int, int]] = []

        def on_epic_done(partial, total):
            seen.append((len(partial.epics), total))

        with pytest.raises(GeminiError):
            await decompose_prd("prd", None, None, "key", on_epic_done=on_epic_done)

        assert seen == [(1, 3)]

    async def test_callback_failure_does_not_break_decomposition(self, monkeypatch):
        skeleton = PlanSkeleton(summary="s", epics=[EpicSkeleton(title="E1", scope="a")])

        async def fake_skeleton(*args, **kwargs):
            return skeleton, {"tokens_in": 0, "tokens_out": 0}

        async def fake_epic_tasks(*args, **kwargs):
            return [_task("t")], {"tokens_in": 0, "tokens_out": 0}

        monkeypatch.setattr(ai, "_generate_skeleton", fake_skeleton)
        monkeypatch.setattr(ai, "_generate_epic_tasks", fake_epic_tasks)

        def broken_callback(partial, total):
            raise RuntimeError("db hiccup")

        result, _ = await decompose_prd("prd", None, None, "key", on_epic_done=broken_callback)
        assert len(result.epics) == 1
