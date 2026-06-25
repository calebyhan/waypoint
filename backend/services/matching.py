import logging
import re

from supabase import Client

from services.ai import generate_embedding

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.75


def _fuzzy_title_match(title_a: str, title_b: str) -> float:
    """Simple word-overlap similarity between two titles."""
    words_a = set(title_a.lower().split())
    words_b = set(title_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    return len(intersection) / max(len(words_a), len(words_b))


def _is_rejected_pair(db: Client, workspace_id: str, task_id: str, issue_id: str | None, pr_id: str | None) -> bool:
    """Check if this match pair was previously rejected."""
    query = db.table("match_proposals").select("id").eq("workspace_id", workspace_id).eq("task_id", task_id).eq("status", "rejected")
    if issue_id:
        query = query.eq("github_issue_id", issue_id)
    if pr_id:
        query = query.eq("github_pr_id", pr_id)
    result = query.execute()
    return bool(result.data)


async def match_issue_to_task(
    db: Client,
    workspace_id: str,
    issue_row: dict,
    gemini_key: str | None,
) -> dict | None:
    """Run the issue matching pipeline: fuzzy → semantic → fallback."""
    tasks = db.table("tasks").select("id, title, embedding").eq("workspace_id", workspace_id).execute()
    if not tasks.data:
        return None

    issue_title = issue_row["title"]
    best_task_id = None
    best_score = 0.0

    for task in tasks.data:
        if _is_rejected_pair(db, workspace_id, task["id"], issue_row["id"], None):
            continue

        fuzzy = _fuzzy_title_match(issue_title, task["title"])
        if fuzzy > best_score:
            best_score = fuzzy
            best_task_id = task["id"]

    if best_score >= SIMILARITY_THRESHOLD:
        return _create_proposal(db, workspace_id, best_task_id, issue_row["id"], None, best_score)

    if gemini_key:
        try:
            issue_embedding = await generate_embedding(issue_title, gemini_key)
            result = (
                db.rpc(
                    "match_tasks_by_embedding",
                    {
                        "query_embedding": issue_embedding,
                        "match_workspace_id": workspace_id,
                        "match_threshold": SIMILARITY_THRESHOLD,
                        "match_count": 1,
                    },
                )
                .execute()
            )
            if result.data:
                top = result.data[0]
                if not _is_rejected_pair(db, workspace_id, top["id"], issue_row["id"], None):
                    return _create_proposal(db, workspace_id, top["id"], issue_row["id"], None, top["similarity"])
        except Exception:
            logger.exception("Semantic matching failed for issue %s", issue_row["number"])

    return None


async def match_pr_to_task(
    db: Client,
    workspace_id: str,
    pr_row: dict,
    gemini_key: str | None,
) -> dict | None:
    """Run the PR matching pipeline: issue-ref → semantic → fallback."""
    pr_title = pr_row.get("title", "")

    refs = re.findall(r"(?:fixes|closes|resolves)\s+#(\d+)", pr_title, re.IGNORECASE)
    for ref_num in refs:
        issue = (
            db.table("github_issues")
            .select("linked_task_id")
            .eq("workspace_id", workspace_id)
            .eq("number", int(ref_num))
            .single()
            .execute()
        )
        if issue.data and issue.data.get("linked_task_id"):
            return _create_proposal(
                db, workspace_id, issue.data["linked_task_id"], None, pr_row["id"], 1.0,
            )

    tasks = db.table("tasks").select("id, title").eq("workspace_id", workspace_id).execute()
    if not tasks.data:
        return None

    best_task_id = None
    best_score = 0.0
    for task in tasks.data:
        if _is_rejected_pair(db, workspace_id, task["id"], None, pr_row["id"]):
            continue
        fuzzy = _fuzzy_title_match(pr_title, task["title"])
        if fuzzy > best_score:
            best_score = fuzzy
            best_task_id = task["id"]

    if best_score >= SIMILARITY_THRESHOLD and best_task_id:
        return _create_proposal(db, workspace_id, best_task_id, None, pr_row["id"], best_score)

    return None


def _create_proposal(
    db: Client,
    workspace_id: str,
    task_id: str,
    issue_id: str | None,
    pr_id: str | None,
    score: float,
) -> dict:
    data: dict = {
        "workspace_id": workspace_id,
        "task_id": task_id,
        "similarity_score": score,
        "status": "pending",
    }
    if issue_id:
        data["github_issue_id"] = issue_id
    if pr_id:
        data["github_pr_id"] = pr_id

    result = db.table("match_proposals").insert(data).execute()
    return result.data[0]
