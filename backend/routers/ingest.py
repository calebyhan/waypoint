import hashlib
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from supabase import Client

from core.crypto import decrypt_or_plaintext
from core.deps import get_current_user
from core.permissions import assert_workspace_active
from core.supabase import get_supabase
from models.decomposition import ProjectContext, TeamMemberInfo
from services.ai import (
    DECOMPOSITION_MODEL,
    GeminiErrorKind,
    classify_exception,
    decompose_prd,
    generate_questions,
)
from services.pdf import extract_text
from services.scheduling import schedule_tasks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces/{workspace_id}/ingest", tags=["ingest"])

# Maps classified Gemini failure kinds to actionable HTTP statuses. Raw
# exception text never reaches the client -- only GeminiError.message does.
AI_ERROR_STATUS = {
    GeminiErrorKind.INVALID_KEY: status.HTTP_400_BAD_REQUEST,
    GeminiErrorKind.QUOTA_EXCEEDED: status.HTTP_429_TOO_MANY_REQUESTS,
    GeminiErrorKind.TIMEOUT: status.HTTP_502_BAD_GATEWAY,
    GeminiErrorKind.SERVER_ERROR: status.HTTP_502_BAD_GATEWAY,
    GeminiErrorKind.BAD_OUTPUT: status.HTTP_502_BAD_GATEWAY,
    GeminiErrorKind.UNKNOWN: status.HTTP_502_BAD_GATEWAY,
}


def ai_http_exception(exc: Exception, extra: dict | None = None) -> HTTPException:
    """Turn any AI-pipeline exception into a clean, typed HTTP error."""
    gerr = classify_exception(exc)
    logger.exception("Gemini call failed: kind=%s", gerr.kind.value)
    detail = {"kind": gerr.kind.value, "message": gerr.message, "retry_after": gerr.retry_after}
    if extra:
        detail.update(extra)
    return HTTPException(status_code=AI_ERROR_STATUS[gerr.kind], detail=detail)


class IngestText(BaseModel):
    content: str
    context: ProjectContext = ProjectContext()


class AnswerQuestions(BaseModel):
    content: str
    context: ProjectContext = ProjectContext()
    answers: dict[str, str]


def _get_gemini_key(db: Client, user_id: str) -> str:
    result = db.table("profiles").select("gemini_api_key").eq("id", user_id).single().execute()
    key = decrypt_or_plaintext(result.data.get("gemini_api_key")) if result.data else None
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gemini API key not configured. Set it in your profile.",
        )
    return key


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


# ~25-30K tokens at ~3.5-4 chars/token: keeps a single PRD comfortably inside
# Gemini's 250K TPM budget (docs/plans/ai-pipeline-reliability.md) and turns a
# runaway paste/PDF into a clean 400 instead of an opaque Gemini-side 429.
MAX_PRD_CHARS = 100_000


def assert_prd_length(content: str) -> None:
    if len(content) > MAX_PRD_CHARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PRD content is too large ({len(content)} chars, max {MAX_PRD_CHARS}). "
                   "Split it into smaller sections.",
        )


def _enrich_context_with_team(db: Client, workspace_id: str, ctx: ProjectContext) -> ProjectContext:
    if ctx.team_members:
        return ctx
    result = db.table("team_members").select("name, role, weekly_capacity_hours").eq("workspace_id", workspace_id).execute()
    if result.data:
        ctx.team_members = [TeamMemberInfo(**row) for row in result.data]
    return ctx


def _assert_membership(db: Client, workspace_id: str, user_id: str):
    result = (
        db.table("workspace_members")
        .select("workspace_id")
        .eq("workspace_id", workspace_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workspace member")


def _log_usage(db: Client, user_id: str, workspace_id: str, model: str, tokens_in: int, tokens_out: int):
    db.table("ai_usage").insert({
        "user_id": user_id,
        "workspace_id": workspace_id,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }).execute()


@router.post("")
async def ingest_text(
    workspace_id: str,
    body: IngestText,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Ingest PRD text and return clarifying questions or cached decomposition."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    gemini_key = _get_gemini_key(db, user["id"])

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content is empty")
    assert_prd_length(content)

    context = _enrich_context_with_team(db, workspace_id, body.context)

    content_h = _content_hash(content)
    cached = (
        db.table("ingestions")
        .select("decomposition")
        .eq("workspace_id", workspace_id)
        .eq("content_hash", content_h)
        .execute()
    )
    cached_decomposition = cached.data[0].get("decomposition") if cached.data else None
    if cached_decomposition and not cached_decomposition.get("partial"):
        return {"cached": True, "decomposition": cached_decomposition}

    try:
        questions_result, usage = await generate_questions(content, context, gemini_key)
        _log_usage(db, user["id"], workspace_id, "gemini-3.1-flash-lite", usage["tokens_in"], usage["tokens_out"])
    except Exception as e:
        raise ai_http_exception(e)

    if questions_result.questions:
        return {"cached": False, "questions": [q.model_dump() for q in questions_result.questions]}

    return await _do_decompose(db, user["id"], workspace_id, content, context, None, gemini_key)


@router.post("/upload")
async def ingest_pdf(
    workspace_id: str,
    file: UploadFile,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Ingest a PDF file — extract text and process like text input."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")

    file_bytes = await file.read()
    content = extract_text(file_bytes)
    if not content.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not extract text from PDF")
    assert_prd_length(content)

    gemini_key = _get_gemini_key(db, user["id"])
    project_context = _enrich_context_with_team(db, workspace_id, ProjectContext())

    try:
        questions_result, usage = await generate_questions(content, project_context, gemini_key)
        _log_usage(db, user["id"], workspace_id, "gemini-3.1-flash-lite", usage["tokens_in"], usage["tokens_out"])
    except Exception as e:
        raise ai_http_exception(e)

    if questions_result.questions:
        return {
            "cached": False,
            "extracted_content": content,
            "questions": [q.model_dump() for q in questions_result.questions],
        }

    return await _do_decompose(db, user["id"], workspace_id, content, project_context, None, gemini_key)


@router.post("/answer")
async def answer_questions(
    workspace_id: str,
    body: AnswerQuestions,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Submit answers to clarifying questions and trigger decomposition."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    gemini_key = _get_gemini_key(db, user["id"])

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content is empty")
    assert_prd_length(content)

    context = _enrich_context_with_team(db, workspace_id, body.context)

    return await _do_decompose(db, user["id"], workspace_id, content, context, body.answers, gemini_key)


async def _do_decompose(
    db: Client,
    user_id: str,
    workspace_id: str,
    content: str,
    project_context: ProjectContext,
    answers: dict[str, str] | None,
    gemini_key: str,
):
    content_h = _content_hash(content)
    progress = {"completed": 0, "total": None}

    def _persist_partial(partial, total_epics: int):
        """Save partial progress after each epic so a mid-sequence failure
        doesn't throw away already-generated (and paid-for) epics."""
        progress["completed"] = len(partial.epics)
        progress["total"] = total_epics
        payload = partial.model_dump()
        payload["partial"] = True
        db.table("ingestions").upsert({
            "workspace_id": workspace_id,
            "content_hash": content_h,
            "raw_content": content,
            "decomposition": payload,
        }, on_conflict="workspace_id,content_hash").execute()

    try:
        result, usage = await decompose_prd(
            content, project_context, answers, gemini_key, on_epic_done=_persist_partial
        )
        _log_usage(db, user_id, workspace_id, DECOMPOSITION_MODEL, usage["tokens_in"], usage["tokens_out"])
    except Exception as e:
        extra = None
        if progress["total"] is not None:
            extra = {"partial_epics_completed": progress["completed"], "total_epics": progress["total"]}
        raise ai_http_exception(e, extra)

    decomposition = result.model_dump()

    project_start = None
    if project_context.start_date:
        try:
            project_start = date.fromisoformat(project_context.start_date)
        except ValueError:
            pass

    all_tasks = [t for epic in decomposition.get("epics", []) for t in epic.get("tasks", [])]
    schedule_tasks(
        all_tasks,
        project_start,
        project_context.tickets_per_member_per_week,
        project_context.assign_day,
    )

    # Persist the schedule settings used for this ingestion onto the workspace
    # itself, so the settings page's timeline section reflects what was
    # actually used to schedule tasks instead of showing the column defaults.
    db.table("workspaces").update({
        "schedule_start_date": project_context.start_date or None,
        "tickets_per_member_per_week": project_context.tickets_per_member_per_week,
        "assign_day": project_context.assign_day,
    }).eq("id", workspace_id).execute()

    # Upsert (not insert): replaces any partial-progress row for this content
    # and collapses concurrent duplicate ingests onto a single cache row.
    db.table("ingestions").upsert({
        "workspace_id": workspace_id,
        "content_hash": content_h,
        "raw_content": content,
        "decomposition": decomposition,
    }, on_conflict="workspace_id,content_hash").execute()

    return {"cached": False, "decomposition": decomposition}
