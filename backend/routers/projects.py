from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from core.deps import get_current_user
from core.supabase import get_supabase
from services.ai import decompose_prd
from services.diff import compute_plan_diff

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
        _materialize_decomposition(db, workspace_id, decomposition)

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
    db.table("epics").delete().eq("id", epic_id).execute()


@router.post("/tasks")
async def create_task(
    workspace_id: str,
    body: TaskCreate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
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
    return result.data[0]


@router.patch("/tasks/{task_id}")
async def update_task(
    workspace_id: str,
    task_id: str,
    body: TaskUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
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
    return result.data[0] if result.data else None


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    workspace_id: str,
    task_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
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

    profile = db.table("profiles").select("gemini_api_key").eq("id", user["id"]).single().execute()
    gemini_key = profile.data.get("gemini_api_key") if profile.data else None
    if not gemini_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gemini API key not configured")

    existing_tasks = db.table("tasks").select("*").eq("workspace_id", workspace_id).execute().data

    try:
        new_decomposition = await decompose_prd(body.content, None, None, gemini_key)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI error: {e}")

    diff = compute_plan_diff(existing_tasks, [e.model_dump() for e in new_decomposition.epics])

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


@router.post("/reingest/approve")
async def approve_reingest(
    workspace_id: str,
    body: ApplyReingestChanges,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Apply PM-approved changes from a re-ingestion diff."""
    _assert_membership(db, workspace_id, user["id"])

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


def _materialize_decomposition(db: Client, workspace_id: str, decomposition: dict):
    """Convert a decomposition JSON into actual epic and task rows."""
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
            db.table("tasks").insert(insert).execute()
