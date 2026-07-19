import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from core.crypto import decrypt_or_plaintext
from core.deps import get_current_user
from core.permissions import assert_workspace_active
from core.supabase import get_supabase
from routers.ingest import _content_hash, _log_usage, ai_http_exception, assert_prd_length
from services.ai import DECOMPOSITION_MODEL, decompose_prd, generate_embeddings
from services.diff import compute_plan_diff
from services.github import get_github_token
from services.github_writeback import create_issue_for_task, update_issue_for_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["projects"])


class EpicCreate(BaseModel):
    title: str
    sort_order: int = 0


class EpicUpdate(BaseModel):
    title: str | None = None
    sort_order: int | None = None


class TaskCreate(BaseModel):
    epic_id: str
    title: str
    description: str | None = None
    motivation: str | None = None
    deliverables: list[str] = []
    important_notes: list[str] = []
    estimated_days: int | None = None
    priority: str = "p1"
    dependencies: list[str] = []
    sort_order: int = 0
    start_date: str | None = None
    end_date: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    estimated_days: int | None = None
    priority: str | None = None
    assignee: str | None = None
    status: str | None = None
    sort_order: int | None = None
    dependencies: list[str] | None = None
    epic_id: str | None = None
    version: int | None = None
    start_date: str | None = None
    end_date: str | None = None


class BulkPlanUpdate(BaseModel):
    epics: list[dict]
    tasks: list[dict]


class SplitTask(BaseModel):
    subtasks: list[TaskCreate]


class MergeTasks(BaseModel):
    task_ids: list[str]
    merged_title: str
    merged_description: str | None = None


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


def _get_optional_gemini_key(db: Client, user_id: str) -> str | None:
    """Best-effort key lookup -- embedding generation is optional, so a
    missing profile/key must never fail the calling endpoint."""
    try:
        result = db.table("profiles").select("gemini_api_key").eq("id", user_id).single().execute()
        return decrypt_or_plaintext(result.data.get("gemini_api_key")) if result.data else None
    except Exception:
        return None


def _github_writeback_context(db: Client, workspace_id: str) -> tuple[dict, str] | None:
    """Returns (workspace, token) if this workspace has a connected repo and a
    usable GitHub token, else None -- callers should skip write-back silently."""
    workspace = db.table("workspaces").select("*").eq("id", workspace_id).single().execute().data
    if not workspace or not workspace.get("repo_owner"):
        return None
    token = get_github_token(db, workspace["owner_id"])
    if not token:
        return None
    return workspace, token


@router.get("/plan")
async def get_plan(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Return the current plan (epics + tasks) for a workspace."""
    _assert_membership(db, workspace_id, user["id"])

    epics = (
        db.table("epics")
        .select("*")
        .eq("workspace_id", workspace_id)
        .order("sort_order")
        .execute()
    )
    tasks = (
        db.table("tasks")
        .select("*")
        .eq("workspace_id", workspace_id)
        .order("sort_order")
        .execute()
    )

    if not epics.data:
        ingestion = (
            db.table("ingestions")
            .select("decomposition")
            .eq("workspace_id", workspace_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if ingestion.data and ingestion.data[0].get("decomposition"):
            return {
                "source": "decomposition",
                "decomposition": ingestion.data[0]["decomposition"],
                "epics": [],
                "tasks": [],
            }

    return {"source": "plan", "epics": epics.data, "tasks": tasks.data}


@router.put("/plan")
async def update_plan_bulk(
    workspace_id: str,
    body: BulkPlanUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Bulk update the plan — used during proposal editing."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)

    for epic_data in body.epics:
        epic_id = epic_data.pop("id", None)
        if epic_id:
            db.table("epics").update(epic_data).eq("id", epic_id).execute()

    for task_data in body.tasks:
        task_id = task_data.pop("id", None)
        if task_id:
            db.table("tasks").update(task_data).eq("id", task_id).execute()

    return {"status": "updated"}


@router.post("/plan/approve")
async def approve_plan(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Approve the plan — materialize decomposition into epics/tasks if needed, set all to open."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)

    epics = db.table("epics").select("id").eq("workspace_id", workspace_id).execute()

    if not epics.data:
        ingestion = (
            db.table("ingestions")
            .select("decomposition")
            .eq("workspace_id", workspace_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not ingestion.data or not ingestion.data[0].get("decomposition"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No plan to approve")

        decomposition = ingestion.data[0]["decomposition"]
        gemini_key = _get_optional_gemini_key(db, user["id"])
        await _materialize_decomposition(db, workspace_id, decomposition, gemini_key)

    db.table("tasks").update({"status": "open"}).eq("workspace_id", workspace_id).execute()

    return {"status": "approved"}


@router.post("/epics")
async def create_epic(
    workspace_id: str,
    body: EpicCreate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    result = db.table("epics").insert({
        "workspace_id": workspace_id,
        "title": body.title,
        "sort_order": body.sort_order,
    }).execute()
    return result.data[0]


@router.patch("/epics/{epic_id}")
async def update_epic(
    workspace_id: str,
    epic_id: str,
    body: EpicUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    result = db.table("epics").update(updates).eq("id", epic_id).execute()
    return result.data[0] if result.data else None


@router.delete("/epics/{epic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_epic(
    workspace_id: str,
    epic_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    db.table("epics").delete().eq("id", epic_id).execute()


@router.post("/tasks")
async def create_task(
    workspace_id: str,
    body: TaskCreate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    insert_data = {
        "workspace_id": workspace_id,
        "epic_id": body.epic_id,
        "title": body.title,
        "description": body.description,
        "motivation": body.motivation,
        "deliverables": body.deliverables,
        "important_notes": body.important_notes,
        "estimated_days": body.estimated_days,
        "priority": body.priority,
        "dependencies": body.dependencies,
        "sort_order": body.sort_order,
    }
    if body.start_date:
        insert_data["start_date"] = body.start_date
    if body.end_date:
        insert_data["end_date"] = body.end_date
    result = db.table("tasks").insert(insert_data).execute()
    task = result.data[0]

    writeback = _github_writeback_context(db, workspace_id)
    if writeback:
        workspace, token = writeback
        await create_issue_for_task(db, workspace, task, token)
        task = db.table("tasks").select("*").eq("id", task["id"]).single().execute().data

    return task


@router.patch("/tasks/{task_id}")
async def update_task(
    workspace_id: str,
    task_id: str,
    body: TaskUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    expected_version = updates.pop("version", None)
    if expected_version is not None:
        current = db.table("tasks").select("version").eq("id", task_id).single().execute()
        if current.data and current.data["version"] != expected_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task was modified by another user. Reload and try again.",
            )
        updates["version"] = expected_version + 1

    result = db.table("tasks").update(updates).eq("id", task_id).execute()
    task = result.data[0] if result.data else None

    if task and task.get("github_issue_id") and ("title" in updates or "description" in updates):
        writeback = _github_writeback_context(db, workspace_id)
        if writeback:
            workspace, token = writeback
            await update_issue_for_task(db, workspace, task, token)

    return task


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    workspace_id: str,
    task_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    db.table("tasks").delete().eq("id", task_id).execute()


@router.post("/tasks/{task_id}/split")
async def split_task(
    workspace_id: str,
    task_id: str,
    body: SplitTask,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Split a task into multiple subtasks, then delete the original."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)

    original = db.table("tasks").select("*").eq("id", task_id).single().execute()
    if not original.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    created = []
    for i, subtask in enumerate(body.subtasks):
        result = db.table("tasks").insert({
            "workspace_id": workspace_id,
            "epic_id": subtask.epic_id or original.data["epic_id"],
            "title": subtask.title,
            "description": subtask.description,
            "estimated_days": subtask.estimated_days,
            "priority": subtask.priority or original.data["priority"],
            "sort_order": original.data["sort_order"] + i,
        }).execute()
        created.append(result.data[0])

    db.table("tasks").delete().eq("id", task_id).execute()
    return {"original_id": task_id, "new_tasks": created}


@router.post("/tasks/merge")
async def merge_tasks(
    workspace_id: str,
    body: MergeTasks,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Merge multiple tasks into a single task."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)

    if len(body.task_ids) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Need at least 2 tasks to merge")

    first_task = db.table("tasks").select("*").eq("id", body.task_ids[0]).single().execute()
    if not first_task.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    total_days = 0
    for tid in body.task_ids:
        t = db.table("tasks").select("estimated_days").eq("id", tid).single().execute()
        if t.data and t.data.get("estimated_days"):
            total_days += t.data["estimated_days"]

    result = db.table("tasks").insert({
        "workspace_id": workspace_id,
        "epic_id": first_task.data["epic_id"],
        "title": body.merged_title,
        "description": body.merged_description,
        "estimated_days": total_days or None,
        "priority": first_task.data["priority"],
        "sort_order": first_task.data["sort_order"],
    }).execute()

    for tid in body.task_ids:
        db.table("tasks").delete().eq("id", tid).execute()

    return result.data[0]


class ReingestRequest(BaseModel):
    content: str


@router.post("/reingest")
async def reingest_prd(
    workspace_id: str,
    body: ReingestRequest,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Decompose an updated PRD and diff it against the existing plan."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)

    profile = db.table("profiles").select("gemini_api_key").eq("id", user["id"]).single().execute()
    gemini_key = decrypt_or_plaintext(profile.data.get("gemini_api_key")) if profile.data else None
    if not gemini_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gemini API key not configured")

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content is empty")
    assert_prd_length(content)

    existing_tasks = db.table("tasks").select("*").eq("workspace_id", workspace_id).execute().data

    # Decomposition cache: identical content re-ingested twice must not
    # re-call Gemini (mirrors the initial-ingest cache in ingest.py).
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
        new_epics = cached_decomposition.get("epics", [])
    else:
        progress = {"completed": 0, "total": None}

        def _persist_partial(partial, total_epics: int):
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
            new_decomposition, usage = await decompose_prd(
                content, None, None, gemini_key, on_epic_done=_persist_partial
            )
            _log_usage(db, user["id"], workspace_id, DECOMPOSITION_MODEL, usage["tokens_in"], usage["tokens_out"])
        except Exception as e:
            extra = None
            if progress["total"] is not None:
                extra = {"partial_epics_completed": progress["completed"], "total_epics": progress["total"]}
            raise ai_http_exception(e, extra)

        db.table("ingestions").upsert({
            "workspace_id": workspace_id,
            "content_hash": content_h,
            "raw_content": content,
            "decomposition": new_decomposition.model_dump(),
        }, on_conflict="workspace_id,content_hash").execute()
        new_epics = [e.model_dump() for e in new_decomposition.epics]

    diff = compute_plan_diff(existing_tasks, new_epics)

    issue_links = {
        i["linked_task_id"]: i["number"]
        for i in db.table("github_issues").select("linked_task_id, number").eq("workspace_id", workspace_id).execute().data
        if i.get("linked_task_id")
    }
    for entry in diff["modified"]:
        task_id = entry["existing_task"]["id"]
        if task_id in issue_links:
            entry["linked_issue_number"] = issue_links[task_id]

    return diff


class ApplyReingestChanges(BaseModel):
    epic_title: str = "Re-ingested Tasks"
    added: list[dict] = []
    removed_task_ids: list[str] = []
    modified: list[dict] = []  # [{task_id, title, description, estimated_days, priority}]
    idempotency_key: str | None = None  # client-generated, one per diff-review session


@router.post("/reingest/approve")
async def approve_reingest(
    workspace_id: str,
    body: ApplyReingestChanges,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Apply PM-approved changes from a re-ingestion diff."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)

    if body.idempotency_key:
        already = (
            db.table("reingest_applications")
            .select("id")
            .eq("workspace_id", workspace_id)
            .eq("idempotency_key", body.idempotency_key)
            .execute()
        )
        if already.data:
            return {"status": "already_applied"}
        db.table("reingest_applications").insert({
            "workspace_id": workspace_id,
            "idempotency_key": body.idempotency_key,
        }).execute()

    for task_id in body.removed_task_ids:
        db.table("tasks").delete().eq("id", task_id).execute()

    for mod in body.modified:
        task_id = mod.pop("task_id")
        db.table("tasks").update(mod).eq("id", task_id).execute()

    if body.added:
        epics = db.table("epics").select("id").eq("workspace_id", workspace_id).order("sort_order", desc=True).limit(1).execute()
        if epics.data:
            target_epic_id = epics.data[0]["id"]
        else:
            epic_result = db.table("epics").insert({"workspace_id": workspace_id, "title": body.epic_title, "sort_order": 0}).execute()
            target_epic_id = epic_result.data[0]["id"]

        for task_data in body.added:
            # Dedup guard: a double-submit (double click / client retry) must
            # not create duplicate rows for the same added task.
            existing = (
                db.table("tasks")
                .select("id")
                .eq("workspace_id", workspace_id)
                .eq("title", task_data["title"])
                .execute()
            )
            if existing.data:
                continue
            db.table("tasks").insert({
                "workspace_id": workspace_id,
                "epic_id": task_data.get("epic_id", target_epic_id),
                "title": task_data["title"],
                "description": task_data.get("description"),
                "motivation": task_data.get("motivation"),
                "deliverables": task_data.get("deliverables", []),
                "important_notes": task_data.get("important_notes", []),
                "estimated_days": task_data.get("estimated_days"),
                "priority": task_data.get("priority", "p1"),
                "status": "open",
            }).execute()

    return {"status": "applied"}


async def _embed_decomposition_tasks(decomposition: dict, gemini_key: str | None) -> list[list[float] | None]:
    """Batch-embed every task in the decomposition (one Gemini call).

    Best-effort: any failure (no key, bad key, quota, network) returns Nones —
    embedding population must never fail plan approval. Tasks left with a NULL
    embedding simply degrade to fuzzy-title matching in matching.py.
    """
    texts = [
        f"{task_data['title']}\n{task_data.get('description') or ''}"
        for epic_data in decomposition.get("epics", [])
        for task_data in epic_data.get("tasks", [])
    ]
    if not texts or not gemini_key:
        return [None] * len(texts)
    try:
        return await generate_embeddings(texts, gemini_key)
    except Exception:
        logger.exception("Task embedding generation failed; materializing without embeddings")
        return [None] * len(texts)


async def _materialize_decomposition(db: Client, workspace_id: str, decomposition: dict, gemini_key: str | None = None):
    """Convert a decomposition JSON into actual epic and task rows.

    approve_plan only (re-)materializes when no epics exist yet for the
    workspace, so a failure partway through must roll back its own inserts —
    otherwise the leftover epic(s) satisfy that guard and every retry
    silently no-ops instead of finishing materialization.
    """
    embeddings = await _embed_decomposition_tasks(decomposition, gemini_key)
    task_index = 0
    try:
        for i, epic_data in enumerate(decomposition.get("epics", [])):
            epic_result = db.table("epics").insert({
                "workspace_id": workspace_id,
                "title": epic_data["title"],
                "sort_order": i,
            }).execute()
            epic_id = epic_result.data[0]["id"]

            for j, task_data in enumerate(epic_data.get("tasks", [])):
                insert = {
                    "workspace_id": workspace_id,
                    "epic_id": epic_id,
                    "title": task_data["title"],
                    "description": task_data.get("description"),
                    "motivation": task_data.get("motivation"),
                    "deliverables": task_data.get("deliverables", []),
                    "important_notes": task_data.get("important_notes", []),
                    "estimated_days": task_data.get("estimated_days"),
                    "priority": task_data.get("priority", "p1"),
                    "assignee": task_data.get("assignee"),
                    "sort_order": j,
                }
                if task_data.get("start_date"):
                    insert["start_date"] = task_data["start_date"]
                if task_data.get("end_date"):
                    insert["end_date"] = task_data["end_date"]
                if task_index < len(embeddings) and embeddings[task_index] is not None:
                    insert["embedding"] = embeddings[task_index]
                task_index += 1
                db.table("tasks").insert(insert).execute()
    except Exception:
        db.table("epics").delete().eq("workspace_id", workspace_id).execute()
        raise
