from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from core.deps import get_current_user
from core.permissions import assert_workspace_active
from core.supabase import get_supabase
from services.github import get_github_token
from services.github_sync import bump_task
from services.github_writeback import sync_task_status_to_github
from services.insights import generate_insights
from services.scheduling import schedule_tasks

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["dashboard"])


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


def _check_task_version(db: Client, task_id: str, expected_version: int | None):
    """Optimistic-locking guard for dashboard quick-actions.

    Mirrors projects.py's update_task: when the client supplies the version it
    last saw and the row has moved on, reject with 409 instead of stomping.
    bump_task() performs the actual increment, so the caller just needs this
    pre-check. A None version keeps the legacy last-write-wins behavior.
    """
    if expected_version is None:
        return
    current = db.table("tasks").select("version").eq("id", task_id).single().execute()
    if current.data and current.data.get("version") != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task was modified by another user. Reload and try again.",
        )


@router.get("/dashboard")
async def get_dashboard(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Aggregated dashboard view: epics with progress, tasks with linked GitHub data."""
    _assert_membership(db, workspace_id, user["id"])

    epics = db.table("epics").select("*").eq("workspace_id", workspace_id).order("sort_order").execute().data
    tasks = db.table("tasks").select("*").eq("workspace_id", workspace_id).order("sort_order").execute().data
    issues = db.table("github_issues").select("*").eq("workspace_id", workspace_id).execute().data
    prs = db.table("github_prs").select("*").eq("workspace_id", workspace_id).execute().data
    proposals = (
        db.table("match_proposals")
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("status", "pending")
        .execute()
        .data
    )

    issue_by_id = {i["id"]: i for i in issues}
    pr_by_task: dict[str, list[dict]] = {}
    for p in prs:
        if p.get("linked_task_id"):
            pr_by_task.setdefault(p["linked_task_id"], []).append(p)

    epic_progress = []
    for epic in epics:
        epic_tasks = [t for t in tasks if t["epic_id"] == epic["id"]]
        done_count = sum(1 for t in epic_tasks if t["status"] == "done")
        epic_progress.append({
            **epic,
            "total_tasks": len(epic_tasks),
            "done_tasks": done_count,
            "progress_pct": round(done_count / len(epic_tasks) * 100) if epic_tasks else 0,
        })

    linked_issue_ids = {task["github_issue_id"] for task in tasks if task.get("github_issue_id")}
    enriched_tasks = []
    for task in tasks:
        enriched_tasks.append({
            **task,
            "linked_issue": issue_by_id.get(task.get("github_issue_id")),
            "linked_prs": pr_by_task.get(task["id"], []),
        })

    unlinked_issues = [i for i in issues if i["id"] not in linked_issue_ids]
    unlinked_prs = [p for p in prs if not p.get("linked_task_id")]

    return {
        "epics": epic_progress,
        "tasks": enriched_tasks,
        "pending_proposals": proposals,
        "unlinked_issues": unlinked_issues,
        "unlinked_prs": unlinked_prs,
    }


@router.get("/insights")
async def get_insights(
    workspace_id: str,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    return generate_insights(db, workspace_id)


class StatusUpdate(BaseModel):
    status: str
    version: int | None = None


@router.patch("/tasks/{task_id}/status")
async def update_task_status(
    workspace_id: str,
    task_id: str,
    body: StatusUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    if body.status not in ("open", "in_review", "done"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
    _check_task_version(db, task_id, body.version)

    before = db.table("tasks").select("status, github_issue_id").eq("id", task_id).single().execute().data
    task = bump_task(db, task_id, {"status": body.status})

    if task and before and task.get("github_issue_id"):
        crossed_done = body.status == "done" and before["status"] != "done"
        crossed_open = before["status"] == "done" and body.status != "done"

        if crossed_done:
            # Waypoint-initiated "done" -- check the linked issue's *current*
            # cached state directly rather than via recompute_task_done_state,
            # since that function always lets GitHub's state win and would
            # silently revert this back to open. This is the one real
            # collision case (decision 2): flag it, don't auto-resolve either way.
            issue = db.table("github_issues").select("*").eq("id", task["github_issue_id"]).single().execute().data
            if issue and issue["state"] == "open":
                reason = f"Task marked done but linked issue #{issue['number']} is open on GitHub"
                task = bump_task(db, task_id, {"github_conflict": True, "github_conflict_reason": reason})
            else:
                workspace = db.table("workspaces").select("*").eq("id", workspace_id).single().execute().data
                token = get_github_token(db, workspace["owner_id"]) if workspace else None
                if workspace and workspace.get("repo_owner") and token:
                    await sync_task_status_to_github(db, workspace, task, token, close=True)
        elif crossed_open:
            # Waypoint-initiated reversal out of done -- unambiguous, just push it.
            workspace = db.table("workspaces").select("*").eq("id", workspace_id).single().execute().data
            token = get_github_token(db, workspace["owner_id"]) if workspace else None
            if workspace and workspace.get("repo_owner") and token:
                await sync_task_status_to_github(db, workspace, task, token, close=False)

    return task


class AssigneeUpdate(BaseModel):
    assignee: str | None = None
    version: int | None = None


@router.patch("/tasks/{task_id}/assignee")
async def update_task_assignee(
    workspace_id: str,
    task_id: str,
    body: AssigneeUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    _check_task_version(db, task_id, body.version)
    return bump_task(db, task_id, {"assignee": body.assignee})


class ScheduleUpdate(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    assignee: str | None = None
    version: int | None = None


@router.patch("/tasks/{task_id}/schedule")
async def update_task_schedule(
    workspace_id: str,
    task_id: str,
    body: ScheduleUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    updates = body.model_dump(exclude_none=True)
    expected_version = updates.pop("version", None)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    _check_task_version(db, task_id, expected_version)
    return bump_task(db, task_id, updates)


class ProposalDecision(BaseModel):
    accept: bool


@router.post("/match-proposals/{proposal_id}/decide")
async def decide_match_proposal(
    workspace_id: str,
    proposal_id: str,
    body: ProposalDecision,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """PM accepts or rejects a proposed issue/PR-to-task link."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)

    proposal = db.table("match_proposals").select("*").eq("id", proposal_id).single().execute()
    if not proposal.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

    new_status = "accepted" if body.accept else "rejected"
    db.table("match_proposals").update({"status": new_status}).eq("id", proposal_id).execute()

    if body.accept:
        if proposal.data.get("github_issue_id"):
            bump_task(db, proposal.data["task_id"], {"github_issue_id": proposal.data["github_issue_id"]})
        if proposal.data.get("github_pr_id"):
            db.table("github_prs").update({"linked_task_id": proposal.data["task_id"]}).eq(
                "id", proposal.data["github_pr_id"]
            ).execute()
            bump_task(db, proposal.data["task_id"], {"status": "in_review"})

    return {"status": new_status}


@router.delete("/tasks/{task_id}/github-link")
async def unlink_task_github(
    workspace_id: str,
    task_id: str,
    kind: str,
    github_pr_id: str | None = None,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Manually sever a task<->GitHub link. Never touches GitHub itself -- the
    issue/PR stays as-is upstream; this only clears Waypoint's pointer so a
    human can re-match later."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)

    if kind == "issue":
        bump_task(db, task_id, {"github_issue_id": None})
    elif kind == "pr":
        if not github_pr_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="github_pr_id required")
        db.table("github_prs").update({"linked_task_id": None}).eq("id", github_pr_id).execute()
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kind must be 'issue' or 'pr'")

    return {"status": "unlinked"}


class ConflictResolution(BaseModel):
    resolution: str


@router.post("/tasks/{task_id}/resolve-conflict")
async def resolve_conflict(
    workspace_id: str,
    task_id: str,
    body: ConflictResolution,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Resolve a flagged github_conflict: keep_waypoint re-pushes Waypoint's
    status to GitHub; keep_github reverts the task's status to match GitHub."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)
    if body.resolution not in ("keep_waypoint", "keep_github"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid resolution")

    task = db.table("tasks").select("*").eq("id", task_id).single().execute().data
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if body.resolution == "keep_github":
        bump_task(db, task_id, {"status": "open", "github_conflict": False, "github_conflict_reason": None})
    else:
        bump_task(db, task_id, {"github_conflict": False, "github_conflict_reason": None})
        if task.get("github_issue_id"):
            workspace = db.table("workspaces").select("*").eq("id", workspace_id).single().execute().data
            token = get_github_token(db, workspace["owner_id"]) if workspace else None
            if workspace and workspace.get("repo_owner") and token:
                await sync_task_status_to_github(db, workspace, task, token, close=True)

    return db.table("tasks").select("*").eq("id", task_id).single().execute().data


class RescheduleRequest(BaseModel):
    start_date: str | None = None
    tickets_per_member_per_week: float = 0
    assign_day: int = -1


@router.post("/reschedule")
async def reschedule_tasks(
    workspace_id: str,
    body: RescheduleRequest,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """Re-run the scheduler on all workspace tasks with updated parameters."""
    _assert_membership(db, workspace_id, user["id"])
    assert_workspace_active(db, workspace_id)

    tasks = (
        db.table("tasks")
        .select("id, title, estimated_days, assignee, dependencies, status")
        .eq("workspace_id", workspace_id)
        .order("sort_order")
        .execute()
        .data
    )
    if not tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No tasks to reschedule")

    project_start = None
    if body.start_date:
        try:
            project_start = date.fromisoformat(body.start_date)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid start_date format")

    schedule_tasks(tasks, project_start, body.tickets_per_member_per_week, body.assign_day)

    for task in tasks:
        db.table("tasks").update({
            "start_date": task.get("start_date"),
            "end_date": task.get("end_date"),
        }).eq("id", task["id"]).execute()

    db.table("workspaces").update({
        "schedule_start_date": body.start_date,
        "tickets_per_member_per_week": body.tickets_per_member_per_week,
        "assign_day": body.assign_day,
    }).eq("id", workspace_id).execute()

    return {"status": "rescheduled", "count": len(tasks)}
