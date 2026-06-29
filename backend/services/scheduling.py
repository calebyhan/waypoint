from datetime import date, timedelta


def _add_weekdays(start: date, days: int) -> date:
    """Return the date that is `days` weekdays after `start` (inclusive of start)."""
    if days <= 0:
        return start
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def _next_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def schedule_tasks(
    tasks: list[dict],
    project_start: date | None = None,
) -> list[dict]:
    """Compute start_date and end_date for each task based on dependencies and assignees.

    Args:
        tasks: list of task dicts, each with at least: title, estimated_days, assignee,
               dependencies (list of title strings).
        project_start: the project start date. Defaults to today.

    Returns:
        The same task list with start_date and end_date set as ISO strings.
    """
    if not tasks:
        return tasks

    start = _next_weekday(project_start or date.today())

    title_to_task: dict[str, dict] = {}
    for t in tasks:
        title_to_task[t["title"]] = t

    resolved_end: dict[str, date] = {}
    assignee_available: dict[str, date] = {}

    visited: set[str] = set()
    order: list[str] = []

    def topo_visit(title: str) -> None:
        if title in visited:
            return
        visited.add(title)
        task = title_to_task.get(title)
        if not task:
            return
        for dep_title in task.get("dependencies") or []:
            if dep_title in title_to_task:
                topo_visit(dep_title)
        order.append(title)

    for title in title_to_task:
        topo_visit(title)

    for title in order:
        task = title_to_task[title]
        est_days = task.get("estimated_days") or 1
        assignee = task.get("assignee") or "__unassigned__"

        earliest = start

        for dep_title in task.get("dependencies") or []:
            if dep_title in resolved_end:
                dep_end = resolved_end[dep_title]
                day_after = _next_weekday(dep_end + timedelta(days=1))
                if day_after > earliest:
                    earliest = day_after

        assignee_free = assignee_available.get(assignee, start)
        if assignee_free > earliest:
            earliest = assignee_free

        earliest = _next_weekday(earliest)
        end = _add_weekdays(earliest, est_days - 1)

        task["start_date"] = earliest.isoformat()
        task["end_date"] = end.isoformat()

        resolved_end[title] = end
        assignee_available[assignee] = _next_weekday(end + timedelta(days=1))

    return tasks
