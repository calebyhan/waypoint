import logging
from datetime import datetime, timezone

from supabase import Client

logger = logging.getLogger(__name__)

BLOCKER_DAYS = 3
STALE_PR_DAYS = 7
PRIORITY_ORDER = {"p0": 0, "p1": 1, "p2": 2}


async def generate_insights_for_all_workspaces(db: Client):
    workspaces = db.table("workspaces").select("id").eq("state", "active").execute()
    for ws in workspaces.data:
        try:
            generate_insights(db, ws["id"])
        except Exception:
            logger.exception("Insight generation failed for workspace %s", ws["id"])


def generate_insights(db: Client, workspace_id: str) -> list[dict]:
    """Rule-based analysis producing a sorted list of actionable insights."""
    tasks = db.table("tasks").select("*").eq("workspace_id", workspace_id).execute().data
    issues = db.table("github_issues").select("*").eq("workspace_id", workspace_id).execute().data
    prs = db.table("github_prs").select("*").eq("workspace_id", workspace_id).execute().data

    insights: list[dict] = []
    now = datetime.now(timezone.utc)

    task_issue_map: dict[str, list[dict]] = {}
    for issue in issues:
        if issue.get("linked_task_id"):
            task_issue_map.setdefault(issue["linked_task_id"], []).append(issue)

    task_pr_map: dict[str, list[dict]] = {}
    for pr in prs:
        if pr.get("linked_task_id"):
            task_pr_map.setdefault(pr["linked_task_id"], []).append(pr)

    task_by_id = {t["id"]: t for t in tasks}

    for task in tasks:
        if task["status"] == "done":
            continue

        created_at = _parse_dt(task["created_at"])
        age_days = (now - created_at).days

        linked_prs = task_pr_map.get(task["id"], [])
        if task["status"] == "open" and age_days > BLOCKER_DAYS and not linked_prs:
            insights.append({
                "type": "blocker",
                "task_id": task["id"],
                "priority": task["priority"],
                "message": f"Task '{task['title']}' is open >{BLOCKER_DAYS} days with no linked PR",
            })

        for dep_id in task.get("dependencies") or []:
            dep = task_by_id.get(dep_id)
            if dep and dep["status"] != "done" and task["status"] in ("in_review", "done"):
                insights.append({
                    "type": "dependency_violation",
                    "task_id": task["id"],
                    "priority": task["priority"],
                    "message": f"Task '{task['title']}' is in progress, but its dependency '{dep['title']}' is still open",
                })

        if not task.get("assignee"):
            insights.append({
                "type": "unassigned",
                "task_id": task["id"],
                "priority": task["priority"],
                "message": f"Task '{task['title']}' has no assignee",
            })

        linked_issues = task_issue_map.get(task["id"], [])
        issue_closed = any(i["state"] == "closed" for i in linked_issues)
        pr_merged = any(p["merged"] for p in linked_prs)
        if issue_closed != pr_merged and (issue_closed or pr_merged):
            insights.append({
                "type": "partial_signal",
                "task_id": task["id"],
                "priority": task["priority"],
                "message": f"Task '{task['title']}': {'issue closed' if issue_closed else 'PR merged'} but {'PR not merged' if issue_closed else 'issue still open'} — is this done?",
            })

    for pr in prs:
        if pr["state"] != "open":
            continue
        updated = _parse_dt(pr.get("created_at", now.isoformat()))
        if (now - updated).days > STALE_PR_DAYS:
            task = task_by_id.get(pr.get("linked_task_id")) if pr.get("linked_task_id") else None
            insights.append({
                "type": "stale_pr",
                "task_id": pr.get("linked_task_id"),
                "priority": task["priority"] if task else "p2",
                "message": f"PR #{pr['number']} has been open >{STALE_PR_DAYS} days without merging",
            })

    insights.sort(key=lambda i: PRIORITY_ORDER.get(i["priority"], 3))
    return insights


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
