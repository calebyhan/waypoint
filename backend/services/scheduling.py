import math
from datetime import date, timedelta


def _add_weekdays(start: date, days: int) -> date:
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


def _next_or_same_weekday_num(d: date, target_weekday: int) -> date:
    """Advance d to the next occurrence of target_weekday (0=Mon .. 4=Fri).
    If d is already that weekday, return d."""
    diff = (target_weekday - d.weekday()) % 7
    return d + timedelta(days=diff)


def schedule_tasks(
    tasks: list[dict],
    project_start: date | None = None,
    tickets_per_member_per_week: float = 0,
    assign_day: int = -1,
) -> list[dict]:
    """Compute start_date and end_date for each task based on dependencies and assignees.

    Args:
        tasks: list of task dicts, each with at least: title, estimated_days, assignee,
               dependencies (list of title strings).
        project_start: the project start date. Defaults to today.
        tickets_per_member_per_week: max tickets a member starts per week.
            0 means no pacing limit (back-to-back scheduling).
            e.g. 1 = one new ticket per week, 2 = one every 2.5 days.
        assign_day: preferred weekday to start tickets (0=Mon .. 4=Fri).
            -1 means no preference. Only applied when pacing is active.
    """
    if not tasks:
        return tasks

    start = _next_weekday(project_start or date.today())

    # Min weekdays between consecutive task starts for the same assignee.
    min_gap_days = 0
    if tickets_per_member_per_week > 0:
        min_gap_days = max(1, math.ceil(5 / tickets_per_member_per_week))

    use_assign_day = 0 <= assign_day <= 4 and tickets_per_member_per_week > 0

    title_to_task: dict[str, dict] = {}
    for t in tasks:
        title_to_task[t["title"]] = t

    resolved_end: dict[str, date] = {}
    assignee_available: dict[str, date] = {}
    assignee_last_start: dict[str, date] = {}

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

        if min_gap_days > 0 and assignee in assignee_last_start:
            paced_start = _add_weekdays(assignee_last_start[assignee], min_gap_days)
            if paced_start > earliest:
                earliest = paced_start

        earliest = _next_weekday(earliest)

        if use_assign_day:
            earliest = _next_or_same_weekday_num(earliest, assign_day)
        end = _add_weekdays(earliest, est_days - 1)

        task["start_date"] = earliest.isoformat()
        task["end_date"] = end.isoformat()

        resolved_end[title] = end
        assignee_available[assignee] = _next_weekday(end + timedelta(days=1))
        assignee_last_start[assignee] = earliest

    return tasks
