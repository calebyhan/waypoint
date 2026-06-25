"""Compute a diff between the existing task plan and a freshly decomposed PRD."""


def _word_overlap(a: str, b: str) -> float:
    words_a, words_b = set(a.lower().split()), set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))

TITLE_MATCH_THRESHOLD = 0.5


def compute_plan_diff(existing_tasks: list[dict], new_epics: list[dict]) -> dict:
    """Align existing tasks against the new decomposition's tasks by title similarity.

    Returns: { unchanged, modified, added, removed } where each entry carries
    enough info for the PM to review (existing task, new task data, and whether
    it's linked to a GitHub issue).
    """
    new_tasks_flat = [
        {"epic_title": epic["title"], **task}
        for epic in new_epics
        for task in epic.get("tasks", [])
    ]

    matched_new_indices: set[int] = set()
    unchanged: list[dict] = []
    modified: list[dict] = []
    removed: list[dict] = []

    for existing in existing_tasks:
        best_idx, best_score = None, 0.0
        for idx, new_task in enumerate(new_tasks_flat):
            if idx in matched_new_indices:
                continue
            score = _word_overlap(existing["title"], new_task["title"])
            if score > best_score:
                best_score, best_idx = score, idx

        if best_idx is not None and best_score >= TITLE_MATCH_THRESHOLD:
            matched_new_indices.add(best_idx)
            new_task = new_tasks_flat[best_idx]
            changed = (
                existing["title"] != new_task["title"]
                or (existing.get("description") or "") != new_task.get("description", "")
                or existing.get("estimated_days") != new_task.get("estimated_days")
                or existing.get("priority") != new_task.get("priority")
            )
            entry = {"existing_task": existing, "new_task": new_task, "similarity": best_score}
            if changed:
                modified.append(entry)
            else:
                unchanged.append(entry)
        else:
            removed.append({"existing_task": existing})

    added = [
        {"new_task": new_tasks_flat[idx]}
        for idx in range(len(new_tasks_flat))
        if idx not in matched_new_indices
    ]

    return {
        "unchanged": unchanged,
        "modified": modified,
        "added": added,
        "removed": removed,
    }
