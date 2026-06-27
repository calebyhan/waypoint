import hashlib

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from supabase import Client

from core.deps import get_current_user
from core.supabase import get_supabase
from services.ai import decompose_prd, generate_questions
from services.pdf import extract_text

router = APIRouter(prefix="/workspaces/{workspace_id}/ingest", tags=["ingest"])


class IngestText(BaseModel):
    content: str


class AnswerQuestions(BaseModel):
    content: str
    answers: dict[str, str]


def _get_gemini_key(db: Client, user_id: str) -> str:
    result = db.table("profiles").select("gemini_api_key").eq("id", user_id).single().execute()
    key = result.data.get("gemini_api_key") if result.data else None
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gemini API key not configured. Set it in your profile.",
        )
    return key


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


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
    gemini_key = _get_gemini_key(db, user["id"])

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content is empty")

    content_h = _content_hash(content)
    cached = (
        db.table("ingestions")
        .select("decomposition")
        .eq("workspace_id", workspace_id)
        .eq("content_hash", content_h)
        .execute()
    )
    if cached.data and cached.data[0].get("decomposition"):
        return {"cached": True, "decomposition": cached.data[0]["decomposition"]}

    try:
        questions_result = await generate_questions(content, gemini_key)
        _log_usage(db, user["id"], workspace_id, "gemini-3.1-flash-lite", 500, 200)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI error: {e}")

    if questions_result.questions:
        return {"cached": False, "questions": [q.model_dump() for q in questions_result.questions]}

    return await _do_decompose(db, user["id"], workspace_id, content, None, gemini_key)


@router.post("/upload")
async def ingest_pdf(
    workspace_id: str,
    file: UploadFile,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Ingest a PDF file — extract text and process like text input."""
    _assert_membership(db, workspace_id, user["id"])

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")

    file_bytes = await file.read()
    content = extract_text(file_bytes)
    if not content.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not extract text from PDF")

    gemini_key = _get_gemini_key(db, user["id"])

    try:
        questions_result = await generate_questions(content, gemini_key)
        _log_usage(db, user["id"], workspace_id, "gemini-3.1-flash-lite", 500, 200)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI error: {e}")

    if questions_result.questions:
        return {
            "cached": False,
            "extracted_content": content,
            "questions": [q.model_dump() for q in questions_result.questions],
        }

    return await _do_decompose(db, user["id"], workspace_id, content, None, gemini_key)


@router.post("/answer")
async def answer_questions(
    workspace_id: str,
    body: AnswerQuestions,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Submit answers to clarifying questions and trigger decomposition."""
    _assert_membership(db, workspace_id, user["id"])
    gemini_key = _get_gemini_key(db, user["id"])

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content is empty")

    return await _do_decompose(db, user["id"], workspace_id, content, body.answers, gemini_key)


async def _do_decompose(
    db: Client,
    user_id: str,
    workspace_id: str,
    content: str,
    answers: dict[str, str] | None,
    gemini_key: str,
):
    try:
        result = await decompose_prd(content, answers, gemini_key)
        _log_usage(db, user_id, workspace_id, "gemini-3.1-flash-lite", 6000, 2000)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI error: {e}")

    decomposition = result.model_dump()

    db.table("ingestions").insert({
        "workspace_id": workspace_id,
        "content_hash": _content_hash(content),
        "raw_content": content,
        "decomposition": decomposition,
    }).execute()

    return {"cached": False, "decomposition": decomposition}
