from services.diff import compute_plan_diff


def make_epic(title, tasks):
    return {"title": title, "tasks": tasks}


def make_task(title, description="", estimated_days=2, priority="p1", deliverables=None, important_notes=None):
    return {
        "title": title,
        "description": description,
        "motivation": "",
        "deliverables": deliverables or [],
        "important_notes": important_notes or [],
        "estimated_days": estimated_days,
        "priority": priority,
        "dependencies": [],
    }


def test_unchanged_task_is_not_modified():
    existing = [{"id": "t1", "title": "Implement JWT login", "description": "Add login endpoint",
                 "estimated_days": 2, "priority": "p0"}]
    new_epics = [make_epic("Auth", [make_task("Implement JWT login", "Add login endpoint", 2, "p0")])]

    diff = compute_plan_diff(existing, new_epics)

    assert len(diff["unchanged"]) == 1
    assert diff["modified"] == []
    assert diff["added"] == []
    assert diff["removed"] == []


def test_changed_description_is_modified_not_unchanged():
    existing = [{"id": "t1", "title": "Implement JWT login", "description": "Old description",
                 "estimated_days": 2, "priority": "p0"}]
    new_epics = [make_epic("Auth", [make_task("Implement JWT login", "New description", 2, "p0")])]

    diff = compute_plan_diff(existing, new_epics)

    assert diff["unchanged"] == []
    assert len(diff["modified"]) == 1
    assert diff["modified"][0]["new_task"]["description"] == "New description"


def test_changed_deliverables_is_modified_not_unchanged():
    existing = [{"id": "t1", "title": "Implement JWT login", "description": "Add login endpoint",
                 "motivation": "", "deliverables": ["POST /api/auth/login"], "important_notes": [],
                 "estimated_days": 2, "priority": "p0"}]
    new_epics = [make_epic("Auth", [make_task(
        "Implement JWT login", "Add login endpoint", 2, "p0",
        deliverables=["POST /api/auth/login", "GET /api/auth/me"],
    )])]

    diff = compute_plan_diff(existing, new_epics)

    assert diff["unchanged"] == []
    assert len(diff["modified"]) == 1


def test_unmatched_existing_task_is_removed():
    existing = [{"id": "t1", "title": "Totally unrelated legacy task", "description": "",
                 "estimated_days": 1, "priority": "p2"}]
    new_epics = [make_epic("Auth", [make_task("Implement JWT login")])]

    diff = compute_plan_diff(existing, new_epics)

    assert len(diff["removed"]) == 1
    assert diff["removed"][0]["existing_task"]["id"] == "t1"
    assert len(diff["added"]) == 1


def test_unmatched_new_task_is_added():
    existing = []
    new_epics = [make_epic("Auth", [make_task("Implement JWT login")])]

    diff = compute_plan_diff(existing, new_epics)

    assert diff["unchanged"] == []
    assert diff["removed"] == []
    assert len(diff["added"]) == 1
    assert diff["added"][0]["new_task"]["title"] == "Implement JWT login"


def test_each_new_task_matched_at_most_once():
    """Two existing tasks shouldn't both claim the same new task."""
    existing = [
        {"id": "t1", "title": "Implement JWT login", "description": "", "estimated_days": 2, "priority": "p0"},
        {"id": "t2", "title": "Implement JWT logout", "description": "", "estimated_days": 1, "priority": "p1"},
    ]
    new_epics = [make_epic("Auth", [make_task("Implement JWT login")])]

    diff = compute_plan_diff(existing, new_epics)

    matched_ids = {e["existing_task"]["id"] for e in diff["unchanged"] + diff["modified"]}
    assert len(matched_ids) <= 1
    assert len(diff["removed"]) == 1
