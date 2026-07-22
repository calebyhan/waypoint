"""Tests for services/scheduling.py: dependency ordering, weekend skipping,
per-assignee pacing, assign_day preference, and cycle detection."""

from datetime import date

from services.scheduling import schedule_tasks

MON = date(2026, 1, 5)  # Monday
THU = date(2026, 1, 8)  # Thursday
SAT = date(2026, 1, 3)  # Saturday


def _task(title, est=1, assignee=None, deps=None):
    return {
        "title": title,
        "estimated_days": est,
        "assignee": assignee,
        "dependencies": deps or [],
    }


def test_empty_task_list_returns_empty_list():
    assert schedule_tasks([]) == []


def test_single_task_starts_on_next_weekday():
    tasks = [_task("A")]
    schedule_tasks(tasks, project_start=SAT)
    # Saturday project start rolls forward to Monday.
    assert tasks[0]["start_date"] == "2026-01-05"
    assert tasks[0]["end_date"] == "2026-01-05"


def test_task_spanning_weekend_skips_saturday_sunday():
    tasks = [_task("A", est=3)]
    schedule_tasks(tasks, project_start=THU)
    # Thu + Fri + (skip Sat/Sun) + Mon = 3 weekdays.
    assert tasks[0]["start_date"] == "2026-01-08"
    assert tasks[0]["end_date"] == "2026-01-12"


def test_linear_dependency_chain_respects_order():
    tasks = [
        _task("A", est=2, assignee="a"),
        _task("B", est=2, assignee="b", deps=["A"]),
        _task("C", est=2, assignee="c", deps=["B"]),
    ]
    schedule_tasks(tasks, project_start=MON)
    by_title = {t["title"]: t for t in tasks}
    assert by_title["B"]["start_date"] > by_title["A"]["end_date"]
    assert by_title["C"]["start_date"] > by_title["B"]["end_date"]


def test_diamond_dependency_waits_for_latest_of_both_parents():
    tasks = [
        _task("A", est=1, assignee="a"),
        _task("B", est=5, assignee="b", deps=["A"]),
        _task("C", est=1, assignee="c", deps=["A"]),
        _task("D", est=1, assignee="d", deps=["B", "C"]),
    ]
    schedule_tasks(tasks, project_start=MON)
    by_title = {t["title"]: t for t in tasks}
    # D must wait for B (the later parent), not C.
    assert by_title["D"]["start_date"] > by_title["B"]["end_date"]
    assert by_title["B"]["end_date"] > by_title["C"]["end_date"]


def test_missing_dependency_title_is_silently_ignored():
    # Documents current behavior: an unknown dependency title (e.g. a
    # Gemini-hallucinated reference) is skipped rather than raising.
    tasks = [_task("A", deps=["Nonexistent Task"])]
    schedule_tasks(tasks, project_start=MON)
    assert tasks[0]["start_date"] == "2026-01-05"


def test_cyclic_dependency_does_not_hang_and_schedules_all_tasks():
    tasks = [
        _task("A", est=2, assignee="a", deps=["B"]),
        _task("B", est=2, assignee="b", deps=["A"]),
    ]
    result = schedule_tasks(tasks, project_start=MON)
    assert all(t.get("start_date") and t.get("end_date") for t in result)


def test_cyclic_dependency_breaks_cycle_deterministically(caplog):
    """The closing edge of the cycle is dropped and warned about; the
    remaining edge is still honored so the surviving order is a real
    dependency order, not an arbitrary one."""
    import logging

    tasks = [
        _task("A", est=1, assignee="a", deps=["B"]),
        _task("B", est=1, assignee="b", deps=["A"]),
    ]
    with caplog.at_level(logging.WARNING, logger="services.scheduling"):
        schedule_tasks(tasks, project_start=MON)

    assert any("Cyclic dependency" in r.message for r in caplog.records)
    by_title = {t["title"]: t for t in tasks}
    # DFS enters A first, so B's back-edge (B -> A) is the one dropped:
    # B schedules first, A still waits on B.
    assert by_title["B"]["start_date"] == "2026-01-05"
    assert by_title["A"]["start_date"] > by_title["B"]["end_date"]


def test_three_node_cycle_terminates_and_keeps_surviving_edges():
    tasks = [
        _task("A", est=1, deps=["C"]),
        _task("B", est=1, deps=["A"]),
        _task("C", est=1, deps=["B"]),
    ]
    result = schedule_tasks(tasks, project_start=MON)
    assert len(result) == 3
    assert all(t.get("start_date") for t in result)


def test_same_assignee_tasks_do_not_overlap():
    tasks = [
        _task("A", est=3, assignee="alice"),
        _task("B", est=3, assignee="alice"),
    ]
    schedule_tasks(tasks, project_start=MON)
    by_title = {t["title"]: t for t in tasks}
    assert by_title["B"]["start_date"] > by_title["A"]["end_date"]


def test_pacing_limits_tickets_per_week():
    tasks = [
        _task("A", assignee="alice"),
        _task("B", assignee="alice"),
        _task("C", assignee="alice"),
    ]
    schedule_tasks(tasks, project_start=MON, tickets_per_member_per_week=1)
    starts = [date.fromisoformat(t["start_date"]) for t in tasks]
    assert starts[0] == MON
    assert starts[1] == date(2026, 1, 12)  # one week later
    assert starts[2] == date(2026, 1, 19)


def test_pacing_zero_means_back_to_back():
    tasks = [
        _task("A", assignee="alice"),
        _task("B", assignee="alice"),
    ]
    schedule_tasks(tasks, project_start=MON, tickets_per_member_per_week=0)
    assert tasks[0]["start_date"] == "2026-01-05"
    assert tasks[1]["start_date"] == "2026-01-06"


def test_fractional_tickets_per_week_rounds_gap_up():
    tasks = [
        _task("A", assignee="alice"),
        _task("B", assignee="alice"),
    ]
    # 0.5 tickets/week -> gap of ceil(5 / 0.5) = 10 weekdays.
    schedule_tasks(tasks, project_start=MON, tickets_per_member_per_week=0.5)
    assert tasks[1]["start_date"] == "2026-01-19"


def test_assign_day_preference_shifts_start_to_target_weekday():
    tasks = [_task("A", assignee="alice")]
    schedule_tasks(tasks, project_start=MON, tickets_per_member_per_week=1, assign_day=2)
    assert date.fromisoformat(tasks[0]["start_date"]).weekday() == 2  # Wednesday


def test_assign_day_ignored_when_pacing_disabled():
    tasks = [_task("A", assignee="alice")]
    schedule_tasks(tasks, project_start=MON, tickets_per_member_per_week=0, assign_day=2)
    assert tasks[0]["start_date"] == "2026-01-05"  # Monday, not pushed to Wednesday


def test_unassigned_tasks_share_the_unassigned_bucket():
    # Two unrelated unassigned tasks serialize against each other via the
    # shared "__unassigned__" bucket -- documents current (intentional) behavior.
    tasks = [_task("A", est=2), _task("B", est=2)]
    schedule_tasks(tasks, project_start=MON)
    assert tasks[1]["start_date"] > tasks[0]["end_date"]


def test_estimated_days_defaults_to_one_when_missing():
    tasks = [{"title": "A", "assignee": None, "dependencies": []}]
    schedule_tasks(tasks, project_start=MON)
    assert tasks[0]["start_date"] == tasks[0]["end_date"] == "2026-01-05"
