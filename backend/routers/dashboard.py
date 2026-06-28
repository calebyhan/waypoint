from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from core.deps import get_current_user
from core.supabase import get_supabase
from services.insights import generate_insights

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

    issue_by_task = {i["linked_task_id"]: i for i in issues if i.get("linked_task_id")}
    pr_by_task = {p["linked_task_id"]: p for p in prs if p.get("linked_task_id")}

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

    enriched_tasks = []
    for task in tasks:
        enriched_tasks.append({
            **task,
            "linked_issue": issue_by_task.get(task["id"]),
            "linked_pr": pr_by_task.get(task["id"]),
        })

    unlinked_issues = [i for i in issues if not i.get("linked_task_id")]
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


@router.patch("/tasks/{task_id}/status")
async def update_task_status(
    workspace_id: str,
    task_id: str,
    body: StatusUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    if body.status not in ("open", "in_review", "done"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
    result = db.table("tasks").update({"status": body.status}).eq("id", task_id).execute()
    return result.data[0] if result.data else None


class AssigneeUpdate(BaseModel):
    assignee: str | None = None


@router.patch("/tasks/{task_id}/assignee")
async def update_task_assignee(
    workspace_id: str,
    task_id: str,
    body: AssigneeUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    result = db.table("tasks").update({"assignee": body.assignee}).eq("id", task_id).execute()
    return result.data[0] if result.data else None


class ScheduleUpdate(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    assignee: str | None = None


@router.patch("/tasks/{task_id}/schedule")
async def update_task_schedule(
    workspace_id: str,
    task_id: str,
    body: ScheduleUpdate,
    user: dict = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _assert_membership(db, workspace_id, user["id"])
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    result = db.table("tasks").update(updates).eq("id", task_id).execute()
    return result.data[0] if result.data else None


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

    proposal = db.table("match_proposals").select("*").eq("id", proposal_id).single().execute()
    if not proposal.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

    new_status = "accepted" if body.accept else "rejected"
    db.table("match_proposals").update({"status": new_status}).eq("id", proposal_id).execute()

    if body.accept:
        if proposal.data.get("github_issue_id"):
            db.table("github_issues").update({"linked_task_id": proposal.data["task_id"]}).eq(
                "id", proposal.data["github_issue_id"]
            ).execute()
        if proposal.data.get("github_pr_id"):
            db.table("github_prs").update({"linked_task_id": proposal.data["task_id"]}).eq(
                "id", proposal.data["github_pr_id"]
            ).execute()
            db.table("tasks").update({"status": "in_review"}).eq("id", proposal.data["task_id"]).execute()

    return {"status": new_status}
