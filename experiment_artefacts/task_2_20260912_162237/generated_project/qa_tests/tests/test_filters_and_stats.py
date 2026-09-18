import datetime

import filters
import stats
import services


def build_three_tasks_for_filters(env):
    ps = env["projects"]
    ts = env["tasks"]
    proj = ps.create_project("Alpha")
    t1 = ts.create_task(proj.id, title="IP-High", priority="High", status="In Progress")
    t2 = ts.create_task(proj.id, title="IP-Med", priority="Medium", status="In Progress")
    t3 = ts.create_task(proj.id, title="TD-High", priority="High", status="To Do")
    return proj, t1, t2, t3


def test_filter_status_and_priority_ac16(env):
    proj, t1, t2, t3 = build_three_tasks_for_filters(env)
    ts = env["tasks"]

    all_tasks = ts.list_tasks(proj.id)
    result = filters.filter_tasks(
        all_tasks,
        status={"In Progress"},
        priorities={"High"},
    )
    ids = {t.id for t in result}
    assert ids == {t1.id}


def test_filter_tags_or_case_insensitive_ac17(env):
    ps = env["projects"]
    ts = env["tasks"]
    proj = ps.create_project("Alpha")
    ui = ts.create_task(proj.id, title="UI", priority="Low", tags=["UI"])
    backend = ts.create_task(proj.id, title="Backend", priority="Low", tags=["Backend"])
    docs = ts.create_task(proj.id, title="Docs", priority="Low", tags=["Docs"])

    all_tasks = ts.list_tasks(proj.id)
    result = filters.filter_tasks(all_tasks, tags_any_of={"ui", "API"})
    ids = {t.id for t in result}
    assert ids == {ui.id}


def test_filter_due_date_range_inclusive_and_excludes_none_ac18(env):
    ps = env["projects"]
    ts = env["tasks"]
    proj = ps.create_project("Alpha")
    d1 = ts.create_task(proj.id, title="D1", priority="Low", due_date="2026-09-10")
    d2 = ts.create_task(proj.id, title="D2", priority="Low", due_date="2026-09-20")
    d3 = ts.create_task(proj.id, title="NoDue", priority="Low")

    all_tasks = ts.list_tasks(proj.id)
    result = filters.filter_tasks(
        all_tasks,
        due_date_start="2026-09-01",
        due_date_end="2026-09-15",
    )
    ids = {t.id for t in result}
    assert ids == {d1.id}


def test_clear_filters_semantics_ac19(env):
    # UI control clearing cannot be asserted via public UI API; instead verify that no filters returns all tasks.
    ps = env["projects"]
    ts = env["tasks"]
    proj = ps.create_project("Alpha")
    t1 = ts.create_task(proj.id, title="A", priority="Low")
    t2 = ts.create_task(proj.id, title="B", priority="High", status="In Progress")

    all_tasks = ts.list_tasks(proj.id)
    # Apply some filter to change the result
    filtered = filters.filter_tasks(all_tasks, priorities={"High"})
    assert {t.id for t in filtered} == {t2.id}

    # Clearing filters semantics: calling with no criteria returns all tasks
    cleared = filters.filter_tasks(all_tasks)
    assert {t.id for t in cleared} == {t1.id, t2.id}


def test_statistics_counts_and_completion_ac20(env):
    ps = env["projects"]
    ts = env["tasks"]
    proj = ps.create_project("Alpha")

    # Create tasks: 2 Done, 1 In Progress, 2 To Do
    td1 = ts.create_task(proj.id, title="TD1", priority="Low")  # To Do
    td2 = ts.create_task(proj.id, title="TD2", priority="Low", due_date="2026-09-10")  # To Do, overdue (incomplete) for today=2026-09-11
    ip = ts.create_task(proj.id, title="IP", priority="Medium", status="In Progress")
    d1 = ts.create_task(proj.id, title="D1", priority="High", status="Done")
    d2 = ts.create_task(proj.id, title="D2", priority="High", status="Done")

    today = datetime.date(2026, 9, 11)
    s = stats.compute_statistics(proj, today=today)

    assert s["todo_count"] == 2
    assert s["in_progress_count"] == 1
    assert s["done_count"] == 2
    assert s["overdue_count"] == 1
    assert s["completion_percent"] == 40


def test_statistics_overdue_and_update_when_done_ac21(env):
    ps = env["projects"]
    ts = env["tasks"]
    proj = ps.create_project("Alpha")

    t = ts.create_task(proj.id, title="Overdue soon", priority="High", due_date="2026-09-10")
    today = datetime.date(2026, 9, 11)

    s1 = stats.compute_statistics(proj, today=today)
    assert s1["overdue_count"] == 1
    assert s1["completion_percent"] == 0

    # Mark as Done; no dependencies in this test
    ts.set_task_status(proj.id, t.id, "Done")
    s2 = stats.compute_statistics(proj, today=today)
    assert s2["overdue_count"] == 0
    assert s2["completion_percent"] == 100